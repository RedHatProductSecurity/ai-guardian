# Beyond IDE Hooks: The AI Guardian SDK

*Extending AI Guardian’s security checks to custom agents, Python programs, and direct LLM integrations.*

IDE hooks are powerful because they sit around a host agent’s lifecycle. They do not cover every program that processes untrusted content, however. A custom Python agent, LangChain pipeline, batch job, or direct model client may run outside the IDE hook boundary.

The AI Guardian SDK provides an additive layer for those programs. It lets an application check content, files, commands, and model interactions from inside its own workflow. Additive is the important word: the SDK does not weaken or replace hook enforcement where hooks already apply.

## A monitored session

A basic SDK workflow creates a monitored session and performs explicit checks:

```python
from ai_guardian.sdk import monitor

with monitor() as session:
    session.check_content(user_input)
    session.check_file("/path/to/input.json")
    session.check_command("example-command --dry-run")
```

The session loads the applicable configuration and returns structured results. Blocked findings can raise a security exception, while detected-but-not-blocked findings may produce warnings depending on the configured action mode.

## Direct and REST modes

The SDK can run checks directly in the current process or delegate them to the AI Guardian daemon through a REST or socket path. Direct mode is straightforward for a small program. A daemon-backed mode can be useful when several processes should share a running service, configuration, and operational view.

The choice is an architectural one. Teams should consider process boundaries, latency, deployment, and how they want violations and traces to be collected.

## Guarded model clients

For supported providers, guarded integrations can intercept model calls and scan prompts and responses without requiring every call site to invoke `check_content()` manually. This is helpful in an agent that makes many model requests or uses a framework abstraction.

The integration should still be treated as one layer in the application design. Validate the client configuration, keep credentials in the approved secret-management system, and make sure the agent’s tools also enforce path and command policy.

## Designing a safe SDK integration

Start by identifying every boundary where untrusted content enters the program and every point where the program can affect the filesystem, shell, network, or external services. Add checks at those boundaries, then test the failure path with inert values.

Do not catch and discard security exceptions merely to keep the agent loop moving. If the application chooses to recover, it should preserve the finding, communicate the problem clearly, and require a safe next step.

The SDK is especially valuable when an organization wants the same security vocabulary across interactive IDE use and automated agent workflows. It brings content checks, command checks, and violation retrieval into application code while leaving policy ownership in the configuration and governance layer.

## When the SDK is the right boundary

The SDK is a good fit when the application itself owns the agent loop or when a model client is used outside a supported IDE. Examples include a service that summarizes uploaded documents, an internal coding assistant, an evaluation harness, or an automation that proposes repository changes.

The design question is not simply “where can a check be added?” It is “which transitions could change the security posture?” A model response that becomes a shell command deserves a different review boundary from a response that is displayed as text. A file read that feeds a model deserves attention even if the final output looks harmless.

By putting checks at those transitions, an application can make its security assumptions explicit. The result is easier to test, easier to observe, and easier to explain to reviewers.

Read more: [SDK Guide](https://ai-guardian.readthedocs.io/en/latest/SDK/), [SDK API Reference](https://ai-guardian.readthedocs.io/en/latest/api/sdk/), and [MCP Security Advisor](https://ai-guardian.readthedocs.io/en/latest/MCP_SERVER/).
