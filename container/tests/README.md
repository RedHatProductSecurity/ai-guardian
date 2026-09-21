# Manual Container and OpenShell CLI Tests

These scripts are opt-in live smoke tests for a developer workstation. They use
the developer's own local runtime and credentials. They are not CI tests and do
not accept credential values on the command line.

## Prerequisites

For OpenShell cases:

- OpenShell CLI installed and connected to a gateway
- OpenShell Providers v2 enabled
- A locally built or published AI Guardian OpenShell image

For Container cases:

- Docker or Podman installed and running
- A locally built or published AI Guardian container image

For either runtime, provide the credentials required by the selected case.

Before running an OpenShell case, check the gateway:

```bash
openshell status
openshell settings set --global --key providers_v2_enabled --value true
```

## Run A Case

From the repository root, run the source checkout with the local development
image:

```bash
python container/tests/test_openshell_agents.py \
    --image localhost/ai-guardian-openshell:dev \
    --case codex
```

The runner automatically uses `uv run ai-guardian` from this checkout. Use
`--ai-guardian-command` only when the installed command should be used instead,
for example `--ai-guardian-command ai-guardian`.

Use the published image by omitting `--image`, or select a different local
image. The runner creates a uniquely named temporary sandbox, bootstraps AI
Guardian, runs the CLI, prints the result, and removes the sandbox and exposed
AI Guardian service afterward.

## Cases

| Case | CLI command | Provider requirement |
| --- | --- | --- |
| `claude` | `claude --bare -p "hello" --model claude-sonnet-4-6` | Claude-compatible provider, API key, or Vertex credentials |
| `codex` | `codex exec --skip-git-repo-check "hello"` | Codex provider or local Codex login |
| `copilot` | `copilot --help` | OpenShell Copilot provider; pass `--provider copilot=NAME` |
| `opencode-claude` | `opencode --agent claude run "hello" --model claude-sonnet-4-6` | Claude/Vertex provider; pass `--provider opencode-claude=NAME` |
| `opencode-openai` | `opencode --agent build run "hello" --model openai/gpt-5.6-luna` | Existing OpenAI-compatible provider, or Codex API-key login through sandbox auto-setup |
| `opencode-openai-api-key` | `opencode --agent build run "hello" --model openai/gpt-5.6-luna` | Host Codex `auth.json` with `OPENAI_API_KEY`; skipped otherwise |
| `pi-anthropic` | `pi -p "hello" --model claude-sonnet-4-6 --provider anthropic` | Anthropic-compatible provider |
| `pi-openai` | `pi -p "hello" --model gpt-5.6-luna --provider openai` | Local Pi OpenAI API-key login |
| `pi-openai-codex` | `pi -p "hello" --model gpt-5.6-luna --provider openai-codex` | Local Pi Codex OAuth login; experimental and may fail with resolver-backed credentials |

Run every OpenShell case with `--all`. Cases requiring an explicit existing
OpenAI-compatible gateway provider are skipped unless a provider name is supplied:

```bash
python container/tests/test_openshell_agents.py \
    --case opencode-openai \
    --provider opencode-openai=my-openai-provider
```

Provider values are names only. The script delegates credential resolution to
AI Guardian and OpenShell; it does not expose credential contents in command
arguments.

The `opencode-openai-api-key` case is skipped unless the host Codex auth file
contains an API key. To exercise automatic `ai-guardian-codex` creation from a
Codex API-key login, use that case or run the documented `ai-guardian sandbox
create` command directly with an OpenAI-shaped model and omit `--provider`.

## Options

- `--case NAME` can be repeated; use `--all` for the full matrix.
- `--prompt TEXT` changes the prompt; the default is `hello`.
- `--provider CASE=NAME` attaches an existing gateway provider.
- `--repo PATH` uploads an optional repository snapshot; it is omitted by default.
- `--keep` retains sandboxes for inspection instead of deleting them.
- `--executor podman` uses `podman exec` when the gateway exposes a local Podman container.
- `--stop-on-failure` stops after the first unexpected failure.
- `--opencode-model`, `--openai-model`, and `--anthropic-model` override defaults.

The default executor is `openshell sandbox exec`, which is portable across
OpenShell compute drivers. Raw `podman exec` is only reliable with a local
Podman-backed gateway and is therefore an optional mode.

The `pi-openai-codex` case is reported as an expected failure when it cannot
consume OpenShell resolver-backed OAuth credentials. Native `codex` remains the
supported OpenShell path for ChatGPT subscriptions, but the experimental Pi
route is selectable for diagnostics.

## Container Cases

Run the broader Docker/Podman matrix from the repository root:

```bash
python container/tests/test_container_agents.py \
    --image localhost/ai-guardian:dev \
    --case codex
```

The Container runner supports these CLI/provider cases:

| Case | CLI command or probe | Credential requirement |
| --- | --- | --- |
| `claude` | `claude --bare -p "hello" --model claude-sonnet-4-6` | Anthropic API key or Vertex ADC |
| `copilot` | `copilot --help` | Copilot installation/token for a model call |
| `codex` | `codex exec --skip-git-repo-check "hello"` | Codex OAuth or OpenAI API key inside the container |
| `gemini` | `gemini --help` | Gemini credentials for a model call |
| `antigravity` | `agy --help` | Antigravity credentials for a model call |
| `kiro` | `kiro-cli --help` | ToS consent and Kiro credentials |
| `openclaw` | `openclaw --help` | OpenClaw credentials for a model call |
| `opencode` | `opencode --agent build run "hello" --model openai/gpt-5.6-luna` | OpenCode provider credentials |
| `pi-anthropic` | `pi -p "hello" --model claude-sonnet-4-6 --provider anthropic` | Anthropic credentials |
| `pi-openai` | `pi -p "hello" --model gpt-5.6-luna --provider openai` | OpenAI API key |
| `pi-openai-codex` | `pi -p "hello" --model gpt-5.6-luna --provider openai-codex` | Local Pi Codex OAuth login |
| `crush` | `crush --help` | Crush credentials for a model call |

Run every Container case one by one with `--all`:

```bash
python container/tests/test_container_agents.py \
    --image localhost/ai-guardian:dev \
    --all
```

The help probes verify image installation and selected-agent setup without
requiring a model credential. Model cases perform a real noninteractive call
and report missing or invalid credentials as failures. Containers are removed
after each case unless `--keep` is supplied.
