#!/usr/bin/env bash
set -euo pipefail

# Create an AI Guardian support image as an OpenShell sandbox.
#
# OpenShell's --upload option transfers a snapshot into the sandbox.  That is
# the closest portable equivalent to a read-only file bind mount: the host
# file is never modified, while the sandbox receives its own copy.  The
# Docker/Podman launcher uses a true read-only bind mount.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
POLICY_COMPOSER="${AI_GUARDIAN_OPEN_SHELL_POLICY_COMPOSER:-${SCRIPT_DIR}/compose_openshell_policy.py}"
POLICY_BASE="${AI_GUARDIAN_OPEN_SHELL_BASE_POLICY:-${SCRIPT_DIR}/policies/base.yaml}"
AGENT_POLICY_DIR="${AI_GUARDIAN_OPEN_SHELL_AGENT_POLICY_DIR:-${SCRIPT_DIR}/policies/agents}"

# OpenShell uses a separate image because its community base image supplies
# the agent binaries and filesystem layout expected by the gateway policy.
# Keep AI_GUARDIAN_IMAGE as the explicit override for custom BYOC images.
IMAGE="${AI_GUARDIAN_IMAGE:-${AI_GUARDIAN_OPEN_SHELL_IMAGE:-quay.io/redhatproductsecurity/ai-guardian-openshell:latest}}"
IDE="${AI_GUARDIAN_AGENT:-${AI_GUARDIAN_IDE:-claude}}"
PROFILE="${AI_GUARDIAN_PROFILE:-}"
REST_PORT="${AI_GUARDIAN_REST_PORT:-0}"
# OpenShell's create --forward option maps one port to the same port inside
# the sandbox. Keep the daemon on its stable internal port and use the
# service-forward command below when the host port is different.
DAEMON_PORT="${AI_GUARDIAN_OPEN_SHELL_DAEMON_PORT:-63152}"
FORWARD_ENABLED="${AI_GUARDIAN_OPEN_SHELL_FORWARD:-true}"
SETUP_SCOPE="${AI_GUARDIAN_SETUP_SCOPE:-selected}"
CONTAINER_CLI="${OPENSHELL_CLI:-openshell}"
OPEN_SHELL_FORWARD_STATE_DIR="${AI_GUARDIAN_OPEN_SHELL_FORWARD_STATE_DIR:-}"
if [[ -z "$OPEN_SHELL_FORWARD_STATE_DIR" ]]; then
    if [[ -n "${XDG_RUNTIME_DIR:-}" ]]; then
        OPEN_SHELL_FORWARD_STATE_DIR="${XDG_RUNTIME_DIR}/ai-guardian/openshell-forwards"
    elif [[ -n "${AI_GUARDIAN_STATE_DIR:-}" ]]; then
        OPEN_SHELL_FORWARD_STATE_DIR="${AI_GUARDIAN_STATE_DIR}/openshell-forwards"
    elif [[ -n "${XDG_STATE_HOME:-}" ]]; then
        OPEN_SHELL_FORWARD_STATE_DIR="${XDG_STATE_HOME}/ai-guardian/openshell-forwards"
    else
        OPEN_SHELL_FORWARD_STATE_DIR="${HOME:-${PWD:-.}}/.local/state/ai-guardian/openshell-forwards"
    fi
fi
# OpenShell exposes /sandbox as writable and may replace the image PATH with a
# reduced path that omits system sbin directories. Keep Codex state in its
# normal sandbox home so helper binaries are not rejected as /tmp files.
CODEX_SANDBOX_HOME="/sandbox/.codex"
REPO_PATH=""
CONFIG_DIR_OVERRIDE=""
API_KEY="${ANTHROPIC_API_KEY:-}"
VERTEX_PROJECT_ID="${ANTHROPIC_VERTEX_PROJECT_ID:-${VERTEX_AI_PROJECT_ID:-}}"
VERTEX_REGION="${CLOUD_ML_REGION:-${VERTEX_AI_REGION:-global}}"
INFERENCE_MODEL="${AI_GUARDIAN_OPEN_SHELL_MODEL:-claude-sonnet-4-6}"
POLICY_PATH=""
POLICY_INPUTS=()
POLICY_DISPLAY="default (gateway/provider profiles)"
POLICY_TEMP_DIR=""
SANDBOX_NAME=""
REPO_WORKDIR_ARGS=()
PROVIDER_ARGS=()
EXPLICIT_PROVIDER_NAMES=()
EXTRA_ARGS=()
HAS_EXPLICIT_PROVIDER="false"
AGENT_PROVIDER_ATTACHED="false"
PROVIDER_ENV_VARS=()
VERTEX_PROVIDER_REQUIRED="false"
VERTEX_PROVIDER_NAME=""

# OpenShell sandboxes are terminal-first.  Keep GUI/editor integrations out
# of this selector even though the image entrypoint can configure their hooks.
# Some entries require a custom base image or the existing runtime consent
# flow because their binaries are not redistributed in the default image.
SUPPORTED_AGENTS=(claude copilot codex gemini kiro openclaw opencode crush)

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

_ensure_sandbox_name() {
    if [[ -n "$SANDBOX_NAME" ]]; then
        return 0
    fi

    # OpenShell limits sandbox names to 19 characters. Keep enough agent
    # identity for operator visibility and a short PID suffix for reuse
    # avoidance while staying below that limit.
    local agent_suffix="${IDE:0:8}"
    local pid_suffix="${BASHPID:-$$}"
    pid_suffix="${pid_suffix: -6}"
    SANDBOX_NAME="ag-${agent_suffix}-${pid_suffix}"
}

_print_help() {
    echo "Usage: $0 [OPTIONS] [-- COMMAND...]"
    echo ""
    echo "Options:"
    echo "  --agent, --ide NAME       Select a CLI agent (default: claude)"
    echo "  --profile NAME             Use a bundled or custom security profile"
    echo "  --config-dir, --guardian-home DIR"
    echo "                             Host ai-guardian config directory"
    echo "  --repo DIR                 Upload a repository snapshot"
    echo "  --port PORT                Forward the daemon port (default: 0/free port)"
    echo "  --no-forward               Keep the daemon REST API inside the sandbox"
    echo "  --base, --image IMAGE      Select the BYOC image"
    echo "  --model MODEL              OpenShell inference model for Vertex Claude"
    echo "  --policy FILE              Add a policy overlay (repeatable)"
    echo "  --name NAME                Name the sandbox"
    echo "  --provider NAME            Attach an OpenShell provider (repeatable)"
    echo "  --                        Run a command instead of the default shell"
    echo ""
    echo "Supported CLI agents: ${SUPPORTED_AGENTS[*]}"
}

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
        --no-forward)
            FORWARD_ENABLED="false"
            shift
            ;;
        --base|--image)
            _require_option_value "$@"
            IMAGE="$2"
            shift 2
            ;;
        --model)
            _require_option_value "$@"
            INFERENCE_MODEL="$2"
            shift 2
            ;;
        --api-key)
            _require_option_value "$@"
            API_KEY="$2"
            shift 2
            ;;
        --policy)
            _require_option_value "$@"
            POLICY_INPUTS+=("$2")
            shift 2
            ;;
        --name)
            _require_option_value "$@"
            SANDBOX_NAME="$2"
            shift 2
            ;;
        --provider)
            _require_option_value "$@"
            PROVIDER_ARGS+=(--provider "$2")
            EXPLICIT_PROVIDER_NAMES+=("$2")
            HAS_EXPLICIT_PROVIDER="true"
            AGENT_PROVIDER_ATTACHED="true"
            shift 2
            ;;
        --help|-h)
            _print_help
            exit 0
            ;;
        --)
            shift
            EXTRA_ARGS=("$@")
            break
            ;;
        *)
            EXTRA_ARGS+=("$1")
            shift
            ;;
    esac
done

case "$FORWARD_ENABLED" in
    1|true|TRUE|yes|YES|on|ON)
        FORWARD_ENABLED="true"
        ;;
    0|false|FALSE|no|NO|off|OFF)
        FORWARD_ENABLED="false"
        ;;
    *)
        echo "Error: AI_GUARDIAN_OPEN_SHELL_FORWARD must be true or false." >&2
        exit 2
        ;;
esac

if [[ "$REST_PORT" = "0" && "$FORWARD_ENABLED" = "false" ]]; then
    # No host port is needed without forwarding. Keep the daemon on a stable
    # sandbox-local port and avoid probing for a host port unnecessarily.
    REST_PORT="63152"
fi

if ! _is_supported_agent "$IDE"; then
    echo "Error: unsupported agent '$IDE'" >&2
    echo "Supported CLI agents: ${SUPPORTED_AGENTS[*]}" >&2
    exit 2
fi

if [[ ${#EXTRA_ARGS[@]} -eq 0 ]]; then
    # Keep the sandbox available for repeated agent sessions and for Git
    # operations after an agent exits.  Pass -- <agent> to launch it directly.
    EXTRA_ARGS=(/bin/bash)
fi

for policy_input in ${POLICY_INPUTS[@]+"${POLICY_INPUTS[@]}"}; do
    if [[ ! -f "$policy_input" ]]; then
        echo "Error: OpenShell policy file not found: $policy_input" >&2
        exit 2
    fi
done

_cleanup_composed_policy() {
    if [[ -n "$POLICY_TEMP_DIR" && -d "$POLICY_TEMP_DIR" ]]; then
        rm -rf -- "$POLICY_TEMP_DIR"
        POLICY_TEMP_DIR=""
    fi
}

trap _cleanup_composed_policy EXIT

_compose_agent_policy() {
    local agent_policy="${AGENT_POLICY_DIR}/${IDE}.yaml"
    local composed_inputs=()

    if [[ ! -f "$POLICY_BASE" ]]; then
        echo "Error: OpenShell base policy not found: $POLICY_BASE" >&2
        return 1
    fi
    if [[ ! -f "$agent_policy" ]]; then
        echo "Error: OpenShell policy fragment not found for agent '$IDE': $agent_policy" >&2
        echo "Set AI_GUARDIAN_OPEN_SHELL_AGENT_POLICY_DIR or add the fragment." >&2
        return 1
    fi
    if [[ ! -f "$POLICY_COMPOSER" ]]; then
        echo "Error: OpenShell policy composer not found: $POLICY_COMPOSER" >&2
        return 1
    fi

    composed_inputs+=("$POLICY_BASE")
    composed_inputs+=( ${POLICY_INPUTS[@]+"${POLICY_INPUTS[@]}"} )
    composed_inputs+=("$agent_policy")

    if ! POLICY_TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ai-guardian-openshell-policy.XXXXXX")"; then
        echo "Error: unable to create a temporary directory for the composed OpenShell policy." >&2
        return 1
    fi
    POLICY_PATH="${POLICY_TEMP_DIR}/policy.yaml"
    if ! python3 "$POLICY_COMPOSER" \
        --output "$POLICY_PATH" \
        "${composed_inputs[@]}"; then
        return 1
    fi

    POLICY_DISPLAY="composed base + ${POLICY_INPUTS[*]-} + ${IDE} agent policy"
}

if ! _compose_agent_policy; then
    exit 2
fi

# Resolve the host ai-guardian configuration directory.  Agent-specific home
# variables are only a fallback for launchers that do not export HOME.
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
CODEX_AUTH_FILE="${CODEX_HOME:-${HOST_HOME}/.codex}/auth.json"

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

CONTAINER_CONFIG_DIR="/sandbox/.config/ai-guardian"
HOST_CONFIG_UPLOADED="false"
CONFIG_SOURCE="sandbox-local"
upload_args=()
if [[ -n "$REPO_PATH" ]]; then
    upload_args+=(--upload "${REPO_PATH}:/sandbox/repo")
    REPO_WORKDIR_ARGS=(--workdir /sandbox/repo)
fi

# Profile selection suppresses the complete host config.  A custom profile
# file is uploaded to a sandbox-local path; built-in profiles need no upload.
PROFILE_IN_SANDBOX="$PROFILE"
if [[ -n "$PROFILE" ]]; then
    case "$PROFILE" in
        @*)
            ;;
        /*|./*|../*)
            if [[ ! -f "$PROFILE" ]]; then
                echo "Error: custom profile file not found: $PROFILE" >&2
                exit 2
            fi
            profile_source="$PROFILE"
            profile_name="${PROFILE##*/}"
            PROFILE_IN_SANDBOX="${CONTAINER_CONFIG_DIR}/profiles/${profile_name}"
            upload_args+=(--upload "${profile_source}:${PROFILE_IN_SANDBOX}")
            CONFIG_SOURCE="profile (host snapshot)"
            ;;
        *)
            profile_candidate="${HOST_CONFIG_DIR}/profiles/${PROFILE}"
            [[ "$profile_candidate" != *.json ]] && profile_candidate="${profile_candidate}.json"
            if [[ -f "$profile_candidate" ]]; then
                profile_name="${profile_candidate##*/}"
                PROFILE_IN_SANDBOX="${CONTAINER_CONFIG_DIR}/profiles/${profile_name}"
                upload_args+=(--upload "${profile_candidate}:${PROFILE_IN_SANDBOX}")
                CONFIG_SOURCE="profile (host snapshot)"
            fi
            ;;
    esac
else
    if [[ -f "$HOST_CONFIG_PATH" ]]; then
        upload_args+=(--upload "${HOST_CONFIG_PATH}:${CONTAINER_CONFIG_DIR}/ai-guardian.json")
        HOST_CONFIG_UPLOADED="true"
        CONFIG_SOURCE="host config (snapshot)"
    elif [[ -n "$CONFIG_DIR_OVERRIDE" || -n "${AI_GUARDIAN_CONFIG_DIR:-}" || -n "${AI_GUARDIAN_HOME:-}" ]]; then
        echo "Notice: host ai-guardian config not found at ${HOST_CONFIG_PATH}; using sandbox-local config" >&2
    fi
fi

# OpenShell only performs command-derived provider discovery when the agent is
# the trailing command of sandbox create. The upload-compatible path starts
# the agent with sandbox exec, so prepare the same provider explicitly for
# agent types advertised by the active gateway.
_agent_provider_type() {
    local profiles

    case "$IDE" in
        claude|codex|copilot|opencode)
            ;;
        *)
            return 1
            ;;
    esac

    if ! profiles="$("$CONTAINER_CLI" provider list-profiles --output json 2>/dev/null)"; then
        return 1
    fi

    if [[ "$IDE" = "claude" ]]; then
        if [[ "$profiles" == *'"id": "claude-code"'* ]]; then
            printf '%s\n' "claude-code"
            return 0
        fi
        if [[ "$profiles" == *'"id": "claude"'* ]]; then
            printf '%s\n' "claude"
            return 0
        fi
        return 1
    fi

    if [[ "$profiles" == *"\"id\""* && "$profiles" == *"\"$IDE\""* ]]; then
        printf '%s\n' "$IDE"
        return 0
    fi
    return 1
}

CODEX_FILE_VARS=()
VERTEX_PROVIDER_SOURCE=""

_read_codex_auth_value() {
    local auth_file="$1"
    local token_key="$2"

    if command -v jq >/dev/null 2>&1; then
        jq -r --arg key "$token_key" '.tokens[$key] // empty' "$auth_file" \
            2>/dev/null
        return $?
    fi

    if command -v python3 >/dev/null 2>&1; then
        python3 -c \
            'import json, sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("tokens", {}).get(sys.argv[2], ""))' \
            "$auth_file" "$token_key" 2>/dev/null
        return $?
    fi

    return 1
}

_set_codex_auth_from_file() {
    local auth_file="$1"
    local env_name="$2"
    local token_key="$3"
    local value

    if [[ -n "${!env_name:-}" ]]; then
        return 0
    fi
    if ! value="$(_read_codex_auth_value "$auth_file" "$token_key")"; then
        return 0
    fi
    if [[ -z "$value" ]]; then
        return 0
    fi

    printf -v "$env_name" '%s' "$value"
    export "$env_name"
    CODEX_FILE_VARS+=("$env_name")
}

_prepare_codex_file_credentials() {
    local codex_home
    local auth_file

    [[ "$IDE" = "codex" ]] || return 0

    codex_home="${CODEX_HOME:-${HOST_HOME}/.codex}"
    auth_file="${codex_home}/auth.json"
    [[ -f "$auth_file" ]] || return 0

    _set_codex_auth_from_file "$auth_file" CODEX_AUTH_ACCESS_TOKEN access_token
    _set_codex_auth_from_file "$auth_file" CODEX_AUTH_REFRESH_TOKEN refresh_token
    _set_codex_auth_from_file "$auth_file" CODEX_AUTH_ACCOUNT_ID account_id
    _set_codex_auth_from_file "$auth_file" CODEX_AUTH_ID_TOKEN id_token
}

_providers_v2_enabled() {
    local settings

    if ! settings="$("$CONTAINER_CLI" settings get --global --json 2>/dev/null)"; then
        return 2
    fi

    if command -v jq >/dev/null 2>&1; then
        jq -e \
            '.settings.providers_v2_enabled == true or .settings.providers_v2_enabled == "true"' \
            <<<"$settings" >/dev/null 2>&1
        return $?
    fi

    if [[ "$settings" =~ "providers_v2_enabled"[[:space:]]*:[[:space:]]*(true|"true") ]]; then
        return 0
    fi
    return 1
}

_require_codex_oauth_support() {
    local settings_status

    [[ "$IDE" = "codex" ]] || return 0
    [[ -z "${OPENAI_API_KEY:-}" ]] || return 0
    [[ -n "${CODEX_AUTH_ACCESS_TOKEN:-}" ]] || return 0

    if _providers_v2_enabled; then
        return 0
    fi
    settings_status=$?
    if [[ "$settings_status" -eq 2 ]]; then
        # Leave the provider command as the source of truth when an older CLI
        # cannot query gateway settings.
        return 0
    fi

    echo "Error: Codex OAuth credentials were found, but OpenShell Providers v2 is disabled on the active gateway." >&2
    echo "Legacy codex provider discovery only recognizes OPENAI_API_KEY." >&2
    echo "Enable it once, then rerun this launcher:" >&2
    echo "  openshell settings set --global --key providers_v2_enabled --value true" >&2
    echo "A Codex OAuth login does not require a separate API key after Providers v2 is enabled." >&2
    return 1
}

_prepare_provider_credentials() {
    _prepare_codex_file_credentials

    if [[ "$IDE" = "claude" && -n "$API_KEY" &&
        -z "${ANTHROPIC_API_KEY:-}" ]]; then
        # --api-key is accepted for parity with run.sh, but the value is
        # exposed only to provider creation and never passed to the sandbox.
        ANTHROPIC_API_KEY="$API_KEY"
        export ANTHROPIC_API_KEY
        PROVIDER_ENV_VARS+=(ANTHROPIC_API_KEY)
    fi
}

_prepare_vertex_provider_credentials() {
    local adc_path

    if [[ -n "${GOOGLE_VERTEX_AI_TOKEN:-}" ||
        -n "${VERTEX_AI_TOKEN:-}" ||
        -n "${GOOGLE_VERTEX_AI_SERVICE_ACCOUNT_TOKEN:-}" ||
        -n "${VERTEX_AI_SERVICE_ACCOUNT_TOKEN:-}" ]]; then
        VERTEX_PROVIDER_SOURCE="from-existing"
        return 0
    fi

    adc_path="${GOOGLE_APPLICATION_CREDENTIALS:-${HOST_HOME}/.config/gcloud/application_default_credentials.json}"
    if [[ ! -f "$adc_path" ]]; then
        echo "Error: Vertex AI was selected, but no gateway-readable GCP credentials were found at ${adc_path}." >&2
        echo "Authenticate with gcloud ADC or provide a compatible OpenShell provider with --provider NAME." >&2
        return 1
    fi

    # OpenShell reads the ADC file while creating the gateway provider.  This
    # variable is not included in sandbox --env arguments.
    if [[ -z "${GOOGLE_APPLICATION_CREDENTIALS:-}" ]]; then
        GOOGLE_APPLICATION_CREDENTIALS="$adc_path"
        export GOOGLE_APPLICATION_CREDENTIALS
        PROVIDER_ENV_VARS+=(GOOGLE_APPLICATION_CREDENTIALS)
    fi
    VERTEX_PROVIDER_SOURCE="from-gcloud-adc"
}

_cleanup_codex_file_credentials() {
    local env_name
    for env_name in ${CODEX_FILE_VARS[@]+"${CODEX_FILE_VARS[@]}"}; do
        unset "$env_name"
    done
    CODEX_FILE_VARS=()
}

_cleanup_provider_credentials() {
    local env_name

    _cleanup_codex_file_credentials
    for env_name in ${PROVIDER_ENV_VARS[@]+"${PROVIDER_ENV_VARS[@]}"}; do
        unset "$env_name"
    done
    PROVIDER_ENV_VARS=()
}

_ensure_agent_provider() {
    local provider_type
    local provider_name="ai-guardian-$IDE"
    local provider_status=0

    if ! provider_type="$(_agent_provider_type)"; then
        echo "Error: the active OpenShell gateway has no provider profile for '$IDE'." >&2
        echo "Create a compatible provider and pass it with --provider NAME." >&2
        return 1
    fi

    if "$CONTAINER_CLI" provider get "$provider_name" >/dev/null 2>&1; then
        echo "Using existing OpenShell provider: $provider_name"
    else
        _prepare_provider_credentials
        if ! _require_codex_oauth_support; then
            _cleanup_provider_credentials
            return 1
        fi
        echo "Creating OpenShell provider from existing local credentials: $provider_name"
        if ! "$CONTAINER_CLI" provider create \
            --name "$provider_name" \
            --type "$provider_type" \
            --from-existing; then
            provider_status=1
        fi
        _cleanup_provider_credentials
        if [[ "$provider_status" -ne 0 ]]; then
            echo "Error: unable to create provider '$provider_name' from existing local credentials." >&2
            echo "Create a compatible provider and pass it with --provider NAME." >&2
            return 1
        fi
    fi

    PROVIDER_ARGS+=(--provider "$provider_name")
    AGENT_PROVIDER_ATTACHED="true"
}

_configure_vertex_provider() {
    local provider_name="$1"

    if ! "$CONTAINER_CLI" provider update "$provider_name" \
        --config "VERTEX_AI_PROJECT_ID=${VERTEX_PROJECT_ID}" \
        --config "VERTEX_AI_REGION=${VERTEX_REGION}"; then
        echo "Error: unable to configure OpenShell Vertex AI provider '$provider_name'." >&2
        echo "The provider requires VERTEX_AI_PROJECT_ID and VERTEX_AI_REGION." >&2
        return 1
    fi
}

_ensure_vertex_provider() {
    local provider_name="ai-guardian-google-vertex-ai"
    local profiles
    local provider_status=0

    if ! profiles="$("$CONTAINER_CLI" provider list-profiles --output json 2>/dev/null)" ||
        [[ "$profiles" != *'"id": "google-vertex-ai"'* ]]; then
        echo "Error: the active OpenShell gateway has no provider profile for 'google-vertex-ai'." >&2
        echo "Create a compatible provider and pass it with --provider NAME." >&2
        return 1
    fi

    if "$CONTAINER_CLI" provider get "$provider_name" >/dev/null 2>&1; then
        echo "Using existing OpenShell provider: $provider_name"
        if ! _configure_vertex_provider "$provider_name"; then
            return 1
        fi
    else
        if ! _prepare_vertex_provider_credentials; then
            return 1
        fi
        echo "Creating OpenShell Vertex AI provider: $provider_name"
        if [[ "$VERTEX_PROVIDER_SOURCE" = "from-gcloud-adc" ]]; then
            if ! "$CONTAINER_CLI" provider create \
                --name "$provider_name" \
                --type google-vertex-ai \
                --from-gcloud-adc \
                --config "VERTEX_AI_PROJECT_ID=${VERTEX_PROJECT_ID}" \
                --config "VERTEX_AI_REGION=${VERTEX_REGION}"; then
                provider_status=1
            fi
        else
            if ! "$CONTAINER_CLI" provider create \
                --name "$provider_name" \
                --type google-vertex-ai \
                --from-existing \
                --config "VERTEX_AI_PROJECT_ID=${VERTEX_PROJECT_ID}" \
                --config "VERTEX_AI_REGION=${VERTEX_REGION}"; then
                provider_status=1
            fi
        fi
        _cleanup_provider_credentials
        if [[ "$provider_status" -ne 0 ]]; then
            echo "Error: unable to create OpenShell Vertex AI provider '$provider_name'." >&2
            echo "Create a compatible provider and pass it with --provider NAME." >&2
            return 1
        fi
    fi

    VERTEX_PROVIDER_NAME="$provider_name"
    PROVIDER_ARGS+=(--provider "$provider_name")
    AGENT_PROVIDER_ATTACHED="true"
}

_configure_vertex_inference() {
    local provider_name="$1"

    echo "Configuring OpenShell inference route: $provider_name / $INFERENCE_MODEL"
    if ! "$CONTAINER_CLI" inference set \
        --provider "$provider_name" \
        --model "$INFERENCE_MODEL" \
        --no-verify; then
        echo "Error: unable to configure OpenShell inference for Vertex AI." >&2
        echo "Verify the provider project/region and selected Vertex model." >&2
        return 1
    fi
}

env_args=(
    --env "AI_GUARDIAN_AGENT=${IDE}"
    --env "AI_GUARDIAN_IDE=${IDE}"
    --env "AI_GUARDIAN_REST_PORT=${DAEMON_PORT}"
    --env "AI_GUARDIAN_CONFIG_DIR=${CONTAINER_CONFIG_DIR}"
    --env "AI_GUARDIAN_HOME=${CONTAINER_CONFIG_DIR}"
    --env "AI_GUARDIAN_SETUP_SCOPE=${SETUP_SCOPE}"
)
if [[ "$IDE" = "claude" ]]; then
    # Claude is supplied by the image and the OpenShell policy keeps the
    # installation path read-only. Update it by rebuilding the image, not
    # from inside the sandbox.
    env_args+=(--env "DISABLE_AUTOUPDATER=1")
fi
if [[ -n "$PROFILE" ]]; then
    env_args+=(--env "AI_GUARDIAN_PROFILE=${PROFILE_IN_SANDBOX}")
fi
if [[ "$HOST_CONFIG_UPLOADED" = "true" ]]; then
    env_args+=(--env "AI_GUARDIAN_HOST_CONFIG_MOUNTED=true")
else
    env_args+=(--env "AI_GUARDIAN_HOST_CONFIG_MOUNTED=false")
fi

if [[ "$IDE" = "codex" ]]; then
    # OpenShell's default filesystem policy can protect the sandbox workdir
    # from writes. Keep Codex's runtime database and temporary arg0 aliases
    # in the explicitly writable area instead of the workdir's .codex.
    env_args+=(--env "CODEX_HOME=${CODEX_SANDBOX_HOME}")
    # OpenShell is already the outer sandbox. Avoid a nested Codex bubblewrap
    # sandbox/user namespace and let the composed OpenShell policy decide
    # which networked commands (for example, git push or gh api) can run.
    env_args+=(--env "AI_GUARDIAN_CODEX_SANDBOX_MODE=danger-full-access")
fi

# OpenShell discovers credentials from the host and injects them through
# providers.  Never place credential values in sandbox --env or --upload
# arguments.  --api-key is handled only while creating a provider below.
# Vertex inference is routed through OpenShell's local privacy router. The
# placeholder API key is deliberately non-secret; the router strips it and
# supplies the gateway-managed provider credential upstream.
if [[ "$IDE" = "claude" && -n "$VERTEX_PROJECT_ID" ]]; then
    VERTEX_PROVIDER_REQUIRED="true"
    env_args+=(
        --env "AI_GUARDIAN_OPEN_SHELL_INFERENCE=true"
        --env "ANTHROPIC_BASE_URL=https://inference.local"
        --env "ANTHROPIC_API_KEY=unused"
    )
fi

UPLOAD_REQUIRED="false"
if (( ${#upload_args[@]} > 0 )); then
    UPLOAD_REQUIRED="true"
fi
if [[ "$UPLOAD_REQUIRED" = "true" ]]; then
    env_args+=(--env "AI_GUARDIAN_OPEN_SHELL_STAGING=true")
fi

if [[ "$VERTEX_PROVIDER_REQUIRED" = "true" ]]; then
    if [[ "$HAS_EXPLICIT_PROVIDER" = "true" ]]; then
        VERTEX_PROVIDER_NAME="${EXPLICIT_PROVIDER_NAMES[0]}"
        if ! _configure_vertex_provider "$VERTEX_PROVIDER_NAME"; then
            exit 2
        fi
    else
        if ! _ensure_vertex_provider; then
            exit 2
        fi
    fi
    if ! _configure_vertex_inference "$VERTEX_PROVIDER_NAME"; then
        exit 2
    fi
fi

if [[ "$UPLOAD_REQUIRED" = "true" ||
    ( "$IDE" = "codex" && -f "$CODEX_AUTH_FILE" &&
        "$HAS_EXPLICIT_PROVIDER" != "true" ) ||
    ( "$IDE" = "claude" &&
        ( -n "$API_KEY" || -n "${CLAUDE_API_KEY:-}" ) &&
        "$HAS_EXPLICIT_PROVIDER" != "true" ) ||
    ( "$IDE" = "copilot" &&
        ( -n "${COPILOT_GITHUB_TOKEN:-}" ||
            -n "${GH_TOKEN:-}" ||
            -n "${GITHUB_TOKEN:-}" ) &&
        "$HAS_EXPLICIT_PROVIDER" != "true" ) ||
    ( "$IDE" = "opencode" &&
        ( -n "${OPENCODE_API_KEY:-}" ||
            -n "${OPENROUTER_API_KEY:-}" ||
            -n "${OPENAI_API_KEY:-}" ) &&
        "$HAS_EXPLICIT_PROVIDER" != "true" ) ]]; then
    # A trailing command is not legal with --upload in OpenShell 0.0.116. A
    # retained, named scratch sandbox is needed for the subsequent upload and
    # exec calls; a name supplied by the caller remains authoritative. The
    # Codex OAuth case also uses an explicit provider when no upload is needed,
    # because command-derived discovery cannot read auth.json by itself.
    _ensure_sandbox_name
    if [[ "$HAS_EXPLICIT_PROVIDER" != "true" &&
        "$VERTEX_PROVIDER_REQUIRED" != "true" ]]; then
        if ! _ensure_agent_provider; then
            exit 2
        fi
    fi
fi

# Providers v2 exposes credentials as opaque placeholders. The image entrypoint
# uses this marker to create the agent-native Codex auth.json from those
# placeholders without copying the host's real OAuth tokens into the sandbox.
if [[ "$IDE" = "codex" && "$AGENT_PROVIDER_ATTACHED" = "true" ]]; then
    env_args+=(--env "AI_GUARDIAN_OPEN_SHELL_PROVIDER=true")
fi

if [[ "$FORWARD_ENABLED" = "true" ]]; then
    # A post-create service forward is required because the host-selected
    # port and the daemon's sandbox-local port are intentionally different.
    _ensure_sandbox_name
fi

if [[ "$UPLOAD_REQUIRED" = "true" || "$AGENT_PROVIDER_ATTACHED" = "true" ]]; then
    openshell_args=(sandbox create --from "$IMAGE" --no-auto-providers)
else
    openshell_args=(sandbox create --from "$IMAGE" --auto-providers)
fi
[[ -n "$SANDBOX_NAME" ]] && openshell_args+=(--name "$SANDBOX_NAME")
[[ -n "$POLICY_PATH" ]] && openshell_args+=(--policy "$POLICY_PATH")
openshell_args+=( ${PROVIDER_ARGS[@]+"${PROVIDER_ARGS[@]}"} )
openshell_args+=("${env_args[@]}")
openshell_args+=( ${upload_args[@]+"${upload_args[@]}"} )

# OpenShell normally infers PTY allocation, but the staged upload path starts
# the agent through a second relay where inference can be lost. Make the
# terminal contract explicit for interactive launches so keyboard protocols
# are handled by Codex (and other full-screen CLIs) instead of echoed to the
# user's shell.
TTY_ARGS=(--no-tty)
if [[ -t 0 && -t 1 ]]; then
    TTY_ARGS=(--tty)
fi
EXEC_ARGS=("${TTY_ARGS[@]}")
EXEC_ARGS+=( ${REPO_WORKDIR_ARGS[@]+"${REPO_WORKDIR_ARGS[@]}"} )

# OpenShell executes the command after the separator directly and does not
# reliably re-enter the image's Docker ENTRYPOINT, especially for detached
# staging. Invoke it explicitly so setup, Codex state initialization, and
# provider placeholder bootstrap happen in the same process that launches the
# agent.
agent_command=(/usr/local/bin/entrypoint.sh "${EXTRA_ARGS[@]}")

_start_service_forward() {
    local forward_log
    local forward_pid
    local attempts=0
    local forward_line
    local forward_port_regex='127\.0\.0\.1:([0-9]+)[[:space:]]+->'

    forward_log="$(mktemp "${TMPDIR:-/tmp}/ai-guardian-openshell-forward.XXXXXX")"
    "$CONTAINER_CLI" forward service \
        --target-port "$DAEMON_PORT" \
        --local "127.0.0.1:${REST_PORT}" \
        "$SANDBOX_NAME" >"$forward_log" 2>&1 &
    forward_pid=$!

    # The service command stays attached while the forward is active. Wait
    # for its ready message so the tray/NiceGUI can use the printed URL as
    # soon as the launcher hands over the interactive shell.
    while [[ "$attempts" -lt 100 ]]; do
        if grep -q "Forwarding" "$forward_log" 2>/dev/null; then
            forward_line="$(grep "Forwarding" "$forward_log" | tail -n 1 || true)"
            if [[ "$forward_line" =~ $forward_port_regex ]]; then
                REST_PORT="${BASH_REMATCH[1]}"
            elif [[ "$REST_PORT" = "0" ]]; then
                cat "$forward_log" >&2
                rm -f -- "$forward_log"
                kill "$forward_pid" 2>/dev/null || true
                echo "Error: OpenShell did not report the dynamically assigned host port." >&2
                return 1
            fi
            _write_forward_state "$forward_pid"
            cat "$forward_log"
            rm -f -- "$forward_log"
            return 0
        fi
        if ! kill -0 "$forward_pid" 2>/dev/null; then
            cat "$forward_log" >&2
            rm -f -- "$forward_log"
            echo "Error: OpenShell service forward failed to start." >&2
            return 1
        fi
        sleep 0.1
        attempts=$((attempts + 1))
    done

    cat "$forward_log" >&2
    kill "$forward_pid" 2>/dev/null || true
    rm -f -- "$forward_log"
    echo "Error: timed out waiting for OpenShell service forward." >&2
    return 1
}

_write_forward_state() {
    local forward_pid="$1"
    local state_path
    local state_file_name

    if ! command -v python3 >/dev/null 2>&1; then
        echo "Warning: python3 is unavailable; host daemon discovery cannot map the OpenShell forward." >&2
        return 0
    fi

    state_file_name="${SANDBOX_NAME//[^A-Za-z0-9_.-]/_}.json"
    state_path="${OPEN_SHELL_FORWARD_STATE_DIR}/${state_file_name}"
    if ! python3 - "$state_path" "$SANDBOX_NAME" "$REST_PORT" "$DAEMON_PORT" "$forward_pid" <<'PY'
import json
import os
import sys
import tempfile

state_path, sandbox_name, local_port, target_port, forward_pid = sys.argv[1:]
state = {
    "sandbox_name": sandbox_name,
    "host": "127.0.0.1",
    "port": int(local_port),
    "target_port": int(target_port),
    "pid": int(forward_pid),
}
state_dir = os.path.dirname(state_path)
os.makedirs(state_dir, mode=0o700, exist_ok=True)
file_descriptor, temporary_path = tempfile.mkstemp(
    prefix=".openshell-forward.", suffix=".tmp", dir=state_dir
)
try:
    with os.fdopen(file_descriptor, "w", encoding="utf-8") as stream:
        json.dump(state, stream, separators=(",", ":"))
        stream.write("\n")
    os.chmod(temporary_path, 0o600)
    os.replace(temporary_path, state_path)
except Exception:
    try:
        os.unlink(temporary_path)
    except OSError:
        # intentionally silent — cleanup of the temporary forward state file
        pass
    raise
PY
    then
        echo "Warning: unable to record the OpenShell forward for host daemon discovery." >&2
    fi
}

_print_forward_details() {
    echo ""
    echo "  Access at: http://127.0.0.1:${REST_PORT}/"
    echo "  Stop with: ${CONTAINER_CLI} forward stop ${REST_PORT}"
}

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  AI Guardian OpenShell Sandbox"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Image:    ${IMAGE}"
echo "  Agent:    ${IDE}"
if [[ "${EXTRA_ARGS[0]:-}" = "/bin/bash" ]]; then
    echo "  Command:  /bin/bash (launch the selected agent manually)"
fi
echo "  Setup:    ${SETUP_SCOPE}"
echo "  Profile:  ${PROFILE:-none (host/default config)}"
echo "  Config:   ${CONFIG_SOURCE}"
echo "  Policy:   ${POLICY_DISPLAY}"
if [[ "$FORWARD_ENABLED" = "true" ]]; then
    if [[ "$REST_PORT" = "0" ]]; then
        echo "  Port:     dynamic (host forward)"
    else
        echo "  Port:     ${REST_PORT} (host forward)"
    fi
else
    echo "  Port:     ${REST_PORT} (not forwarded)"
fi
[[ -n "$REPO_PATH" ]] && echo "  Repo:     ${REPO_PATH} (uploaded snapshot)"
[[ "$UPLOAD_REQUIRED" = "true" ]] && echo "  OpenShell: staged upload followed by sandbox exec"
echo ""

if [[ "$UPLOAD_REQUIRED" = "true" || "$FORWARD_ENABLED" = "true" ]]; then
    if "$CONTAINER_CLI" "${openshell_args[@]}" --detach; then
        :
    else
        status=$?
        exit "$status"
    fi
    # The create call has already read the policy. Remove the local composed
    # copy before handing control to the long-running sandbox exec relay.
    _cleanup_composed_policy
    if [[ "$FORWARD_ENABLED" = "true" ]]; then
        if ! _start_service_forward; then
            exit 1
        fi
        _print_forward_details
    fi
    exec "$CONTAINER_CLI" sandbox exec --name "$SANDBOX_NAME" "${EXEC_ARGS[@]}" -- "${agent_command[@]}"
fi

if [[ -n "$POLICY_TEMP_DIR" ]]; then
    # Do not exec here: the composed policy is a host-side temporary file and
    # must be removed after OpenShell has consumed it.
    if "$CONTAINER_CLI" "${openshell_args[@]}" "${EXEC_ARGS[@]}" -- "${agent_command[@]}"; then
        status=0
    else
        status=$?
    fi
    _cleanup_composed_policy
    exit "$status"
fi

exec "$CONTAINER_CLI" "${openshell_args[@]}" "${EXEC_ARGS[@]}" -- "${agent_command[@]}"
