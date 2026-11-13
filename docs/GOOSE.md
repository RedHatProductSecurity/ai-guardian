# Goose CLI support

AI Guardian supports **Goose v1.59.0 host CLI command hooks on Linux and macOS**.
The integration key and executable are `goose`; a model/provider is not an agent
alias. Desktop, native Windows, hosted/remote Goose, normal Docker/Podman
sandboxes, and OpenShell are **not qualified**. Product runtime selectors exclude
Goose. This is agent-level enforcement, not an outer sandbox.

## Setup and scope

```bash
ai-guardian setup --ide goose --yes
ai-guardian doctor
```

Restart Goose after setup. Default setup creates only the user's owned
`~/.agents/plugins/ai-guardian-goose/` plugin, never project files. To select a
project explicitly:

```bash
ai-guardian setup --ide goose --project /path/to/repository --yes
```

The plugin contains `plugin.json`, `hooks/hooks.json`, and (unless `--no-mcp`)
`.mcp.json`. Setup merges recognized AI Guardian hook actions and the
`ai-guardian` MCP entry, preserves unrelated actions/settings, backs up changes,
and refuses unrecognized manifests, malformed configuration, and linked managed
paths. Current setup is idempotent. Reconciliation repairs owned stale/missing
actions without rewriting unrelated plugins or Goose enablement preferences.
Doctor/tray health distinguishes effective hooks from supplemental MCP setup;
configuration health does not prove that a running Goose has reloaded them.
Malformed sibling hook actions are unhealthy because Goose can reject the whole
hook file. Custom manifest MCP layouts are preserved but reported unverified;
the supported advisor registration uses only the managed default `.mcp.json`.

Enabled project plugins precede user plugins and deduplicate by directory name.
An enabled project `ai-guardian-goose` shadows the user's hooks **and** MCP;
a config-disabled project copy does not. Project-local plugin settings override
project settings, then user settings. Malformed or unverifiable settings are
reported unhealthy, not silently repaired.

## Paths

| Surface | Default |
|---|---|
| User plugin | `~/.agents/plugins/ai-guardian-goose/` |
| Project plugin | `<project>/.agents/plugins/ai-guardian-goose/` |
| Linux configuration | `${XDG_CONFIG_HOME:-~/.config}/goose/config.yaml` |
| macOS configuration | `~/Library/Application Support/Block/goose/config.yaml` |
| User plugin settings | `~/.config/goose/settings.json` (not XDG-relocated) |
| Project/local settings | `<project>/.config/goose/settings.json`, `settings.local.json` |

An **absolute** `GOOSE_PATH_ROOT` relocates the process root: configuration becomes
`<root>/config/`, plugins `<root>/.agents/plugins/`, and user plugin settings
`<root>/.config/goose/settings.json`. Relative values are ignored, as upstream
does. Project selection is not relocated. Use the same environment for setup,
Goose, and the daemon/tray that verifies it.

## Enforcement contract

| Installed event | Behavior |
|---|---|
| `PreToolUse` | Gate native/MCP tools; `{"decision":"allow"}` or `{"decision":"block","reason":"…"}` on stdout, exit 0 |
| `UserPromptSubmit` | Observe `message`; no prompt denial, rewrite, or context injection |
| `PostToolUse` | Observe structured `tool_output`; no output withholding/redaction |
| `SessionStart`, `SessionEnd` | Lifecycle bookkeeping only |

JSON stdin contains `event`, `session_id`, `working_dir`, `tool_name`, `tool_input`,
`tool_call_id`, and event-specific content. Native `shell`, `write`, `edit`,
`tree`, and `read_image` map to shared command/file checks. Edit's `before`/`after`
become old/new content. Relative file paths use `working_dir`; remote images
receive URL checks. Namespaced extension tools retain MCP identity rather than
being mistaken for native shell/file tools.
Native file paths keep `~` literal, matching Goose rather than shell expansion.
Adapter normalization and managed hook-path construction do not probe input paths.
Native paths retain linked `..` components until the shared security guards
canonicalize and check the actual target; file URLs use the platform's decoder.

The managed pre-tool action pins **360 seconds** and `on_failure: "block"`.
Nonzero startup/scan failures, malformed requests/responses, missing executable,
and timeouts remain failures so Goose applies this fail-closed policy. This
differs from Goose's default fail-open behavior and does not inherit AI Guardian's
generic fail-open fallback. Passive actions pin 60 seconds and return no decisions.
This policy applies only while Goose has loaded the enabled action; a missing or
unloadable plugin itself is not a security gate and is reported unhealthy.
Goose forwards denial reasons to the model; they contain only a generic violation
category, never findings, credentials, paths, scanner exceptions, or security
configuration advice.

**`Stop` is not installed.** Blocking it asks Goose to continue generating, not
withhold the already generated response. `BeforeReadFile`, `BeforeShellExecution`,
and other passive callbacks are not additional gates. No prompt/output containment
or transcript protection is claimed. Arbitrary shell scripts/MCP servers retain
the shared scanner's limits; this is not a subprocess filesystem sandbox.

## MCP, hints, protection, and removal

The plugin's `.mcp.json` uses `mcpServers.ai-guardian` to launch
`ai-guardian mcp-server`. The adapter maps Goose's prefixed managed extension
name back to its stable MCP identity. MCP is **advisory**, not a hook alternative.

Explicit `--rules` installs advisory guidelines in the **user configuration's**
`.goosehints`, never project hints (even with project hook setup). Existing hints
are preserved unless replacement was requested. There is no AI Guardian
transcript/session adapter: Goose's session storage is not compatible JSONL.

The general configuration inventory covers Goose configuration, plugin controls,
project hints, and user/project plugin trees. The owned security plugin and all
four hook-control file paths listed above remain immutable for agent-originated
mutations independently of the broader agent-configuration preference, **even
before plugin installation**. This includes the entire `config.yaml`, not just
its plugin settings. The inventory does not probe the request-selected plugin
directory to determine installation. Unrelated plugins, other provider files,
and project hints are outside this narrow immutable scope. This reserves paths;
it does not make an absent or unloaded plugin enforce hooks.
Attempts to invoke the active `goose` CLI from agent tools receive shared host-CLI
protection. Operator-only
[recovery](UNINSTALL.md) removes recognized owned hook/MCP actions and manifests,
not unrelated plugins, preferences, hints, or session data. A missing executable
**blocks pre-tool calls** until the operator repairs/removes the registration.

## Validation and legal review

Isolated adapter/setup/UX tests cover allow/deny, failure boundaries, passive
events, scope/relocation, disabled/shadowed plugins, idempotence, and preservation.
Release Readiness includes installed-command E2E and a **smoke-only** Goose
1.59.0 image using `scripts/agent-cli-test --cli-name goose --agent default
--image IMAGE`: native shell offers, a denied synthetic credential command
without an execution witness, and a clean executed tool/result round-trip must
all be confirmed. No external network, host mounts, credentials, or published
ports are present. Prompt denial and output redaction are tested exclusions.
Real CLI/container scenarios run in CI/manual checks, not routine local tests.
Live macOS execution, desktop, and native Windows remain unverified.

[Goose v1.59.0](https://github.com/aaif-goose/goose/releases/tag/v1.59.0) is
[Apache-2.0](https://github.com/aaif-goose/goose/blob/v1.59.0/LICENSE), compatible
with AI Guardian's Apache-2.0 license. No Goose library is embedded or added as a
Python dependency. Normal releases do not redistribute Goose; the temporary CI
overlay retains its license. No proprietary CLI installation consent is required
for Goose itself. Model/provider, extension, and service terms, credentials, and
telemetry choices remain the operator's separate responsibility; setup does not
change those preferences. The smoke uses only a loopback mock and synthetic
credentials, preserving other agents' consent gates.

Pinned references: [hooks](https://github.com/aaif-goose/goose/blob/v1.59.0/crates/goose/src/hooks/mod.rs),
[discovery/settings](https://github.com/aaif-goose/goose/blob/v1.59.0/crates/goose/src/plugins/discovery.rs),
[Open Plugins](https://github.com/aaif-goose/goose/blob/v1.59.0/crates/goose/src/plugins/formats/open_plugins.rs),
[MCP](https://github.com/aaif-goose/goose/blob/v1.59.0/crates/goose/src/plugins/mcp_servers.rs),
[paths](https://github.com/aaif-goose/goose/blob/v1.59.0/crates/goose/src/config/paths.rs),
[native tools](https://github.com/aaif-goose/goose/blob/v1.59.0/crates/goose/src/agents/platform_extensions/developer/mod.rs).
