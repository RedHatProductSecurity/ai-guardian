# One Security Layer, Many Agents

*How AI Guardian protects different coding assistants through adapters, hooks, and capability-aware integrations.*

AI coding tools do not share one hook format. One agent may call an event `PreToolUse`, another may use a plugin callback, and another may expose only an MCP interface. If every integration implemented its own security logic, the project would be difficult to maintain and difficult to compare.

AI Guardian addresses this with a hook-adapter architecture. Each supported agent has an adapter that translates its input into a normalized internal representation. The core pipeline can then apply common checks for prompts, tools, paths, content, and outputs.

## What an adapter normalizes

The normalized data can include the event type, tool name, tool input, file path, working directory, session identifier, prompt text, tool response, transcript path, and original hook data. This gives the scanners a consistent vocabulary even when the host agent uses different field names.

The adapter also determines how a decision is returned to the host. Some integrations can display a denial message directly. Others have different response formats or expose only part of the lifecycle.

## Capability is not identical across agents

The supported-agent matrix is more useful than a simple list of names. It shows which agents support prompt checks, pre-tool checks, post-tool checks, transcripts, MCP registration, or only partial hook coverage.

For example, an agent with a full pre- and post-tool lifecycle can receive broader protection than an MCP-only integration. A commit-time integration can scan staged files but cannot observe every interactive action. A desktop application may share MCP configuration with a CLI while still having a separate hook boundary.

Readers should always check the current matrix for the specific version and environment they use. “Supported” means the integration exists; it does not necessarily mean every security feature has identical timing or visibility.

## Setup and verification

The setup command normally installs the host-specific hooks or integration:

```bash
ai-guardian setup --ide <agent-name>
```

After setup, verify the generated integration, start the daemon if the environment uses one, and inspect the Console or doctor output. A small harmless test is preferable to a complex end-to-end experiment. Confirm which events are actually being received and where a violation appears.

## Why the adapter model matters

The adapter layer lets the security logic evolve independently from agent-specific plumbing. It also gives teams a clear place to look when behavior differs between tools: first inspect the integration’s capability matrix, then inspect the normalized event and response behavior.

That transparency is valuable for responsible adoption. AI Guardian can provide a common security posture across a mixed toolchain, but the exact coverage still depends on the host agent’s extension points.

## Choosing an integration by workflow

The “best” integration is the one that matches how a team actually works. An interactive coding team may value prompt, pre-tool, and post-tool coverage. A CI-oriented workflow may care more about staged-file scanning and machine-readable results. A team using several agents may prioritize consistent policy concepts and a clear capability matrix over identical behavior at every event.

This is why integration documentation should be read as a capability contract. Before rollout, compare the events the agent exposes with the actions that matter in the project. Then document the boundaries that remain outside the integration, such as external dashboards, cloud agents, or application-specific tool calls.

A common policy layer is valuable, but accurate expectations are more valuable still. Teams can make sound decisions when they know precisely where protection begins and ends.

Read more: [Agent Support](https://ai-guardian.readthedocs.io/en/latest/AGENT_SUPPORT/), [Hooks](https://ai-guardian.readthedocs.io/en/latest/HOOKS/), and [IDE Integration Checklist](https://ai-guardian.readthedocs.io/en/latest/IDE_INTEGRATION_CHECKLIST/).
