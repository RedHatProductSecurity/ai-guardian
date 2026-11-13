# AI Guardian

<p align="center">
  <img src="https://raw.githubusercontent.com/RedHatProductSecurity/ai-guardian/main/images/ai-guardian-320.png" alt="AI Guardian Logo" width="320">
</p>

> Security controls for AI coding agents: hooks scan prompts and tool activity, enforce permissions, and detect sensitive data.

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![PyPI version](https://badge.fury.io/py/ai-guardian.svg)](https://pypi.org/project/ai-guardian/)

## Documentation and Q&A

- [Full documentation site (latest stable release)](https://ai-guardian.readthedocs.io/en/stable/) — searchable,
  versioned guides.
- [Latest documentation (tracks `main`)](https://ai-guardian.readthedocs.io/en/latest/) — guides for upcoming
  development changes.
- [Source documentation index][docs-index] — browse the documentation in this repository.
- [Ask questions about the documentation in NotebookLM](https://notebook.google.com/notebook/9b78ebca-d327-4df7-8f2e-64e518f2ddcb) — a Google account is required.
- [Use the combined documentation export with a private LLM tool][docs-export] — upload this generated single-file compilation to your organization's approved private NotebookLM instance or other LLM search tool. It is generated during releases; do not edit it directly.

## Security Disclaimer

**AI Guardian is one layer of defense in depth, not a guarantee against every
threat.** Detection may miss novel or obfuscated attacks, and secret coverage
depends on available scanner patterns. By design, scanner errors fail open so
development remains available. Combine AI Guardian with code review, CI/CD
scanning, network controls, and secret management. See [Security Design][design]
for architecture and limitations.

## Quick Start

```bash
uv tool install ai-guardian
ai-guardian setup --create-config --install-scanner
ai-guardian daemon start -b
```

Setup detects supported IDEs and guides hook setup. Open your IDE to start using
AI Guardian. For optional desktop controls, run `ai-guardian tray start -b`; open
the browser console with `ai-guardian console`.

> **MCP servers and Skills are blocked by default.** Built-in tools (Bash, Read,
> Write, Edit) are allowed and scanned by hooks. See [Tool Policy][policy]
> for the security posture and configuration.

## Per-integration behavior and limitations

**Supported does not mean identical enforcement.** Protection requires the
hooks/plugins to be installed, enabled, trusted where applicable, and loaded in
the actual execution scope. A local installation does not automatically protect
cloud jobs.

**Legend:**

- **Gate** can stop the action before it starts. **Replace/withhold** changes the
  model-visible prompt or result; it is not a native prompt denial or a rollback.
- **Advice/observe** adds context or scans activity without enforcing a gate or
  replacing a result.
- **Conditional** depends on the host path/configuration. **Unverified** must not
  be relied on for enforcement.
- **Not installed/unavailable** means no AI Guardian hook coverage at that stage.

| Integration / surface | Prompt handling | Pre-tool enforcement | Post-tool result handling | Key limitation |
|---|---|---|---|---|
| Claude Code | Gate | Gate | Feedback or replace supported results | Bash replacement is currently ignored; a post-tool block alone leaves the original result visible. |
| Cursor desktop / local CLI | Gate | Gate | Replace supported MCP results only | No general built-in result replacement; backend-hosted HTTP MCP results cannot be replaced locally. |
| Cursor Cloud Agent | Unavailable | Conditional gate | Supported MCP replacement only; not backend-hosted HTTP MCP | Requires loaded project/cloud-workspace hooks; local user hooks do not protect cloud runs. |
| GitHub Copilot CLI / local command hooks | Observe only | Gate | Not installed | Prompt-hook output is ignored; it cannot block or rewrite the prompt. |
| GitHub Copilot cloud coding-agent job | Not installed | Not installed | Not installed | Local setup does not provision remote job hooks. |
| Grok Build | Observe only | Gate | Observe only | Passive-event output is ignored; project hooks require trust. |
| Codex CLI / desktop Codex mode | Gate | Gate | Replace with feedback, not a sanitized copy | Codex hooks require review/trust and do not cover regular ChatGPT mode. |
| ChatGPT desktop — regular mode | Unavailable | Unavailable | Unavailable | Outside the Codex hook surface; shared MCP configuration does not add hook enforcement. |
| Windsurf Cascade | Gate | Gate | Observe only | Post-hooks cannot block or replace completed results. |
| Gemini CLI | Gate | Gate | Withhold with a fixed refusal | Does not deliver AI Guardian's sanitized copy of a sensitive result. |
| Antigravity CLI (`agy`) | Advice only | Gate | Observe only; no result content | Prompt advice does not terminate the model request; post-hooks cannot inspect tool output. |
| Cline | Observe only | Gate | Observe only; no verified replacement | Script-hook prompt cancellation and result replacement are not documented host contracts. |
| ZooCode | Unverified | Intended gate; unverified | Unverified replacement | Shared Cline scripts are not independently qualified for the exact ZooCode runtime. |
| Kiro IDE | Gate | Gate | Advice/context only | Post-hook context is not result replacement. |
| Kiro CLI | Observe/advice only | Gate | Advice/context only | Prompt Submit cannot block; hook availability varies by CLI generation. |
| AiderDesk extension | Gate | Conditional gate | Replace where the callback runs | Requires v0.55.0+ and an enabled extension; execution paths differ in callback coverage. |
| OpenClaw Gateway plugin | Observe only | Gate | Observe only | Prompt-event return values are ignored; the loaded plugin does not replace post-tool results. |
| OpenCode V1 (1.x) | Replace with a fixed refusal | Gate | Conditional transformation | An explicit replacement can be applied; a post-hook block is not a verified safe-redaction guarantee. |
| OpenCode V2 (2.x) | Replace with a fixed refusal | Gate | Replace/withhold | Requires V2 plugin discovery and artifacts; V1 plugin code does not run in V2. |
| Pi extension | Gate | Gate | Replace or mark as error | Requires a loaded extension; commands handled before the input event are outside its prompt gate. |
| Augment / Auggie local hooks | Not installed | Gate for selected tools | Feedback only; no replacement | Installed matchers do not cover every tool. |
| Crush | Not installed | Gate | Not installed | AI Guardian installs only the pre-tool stage. |
| Goose host CLI | Observe only | Gate | Observe only | v1.59.0 Linux/macOS only; requires an enabled plugin with the fail-closed pre-tool action. Desktop/native Windows and product container/OpenShell runtimes are unqualified. |
| Junie | Not installed | Not installed | Not installed | MCP-only advisory checks depend on the agent choosing to call and follow them; no enforced hooks. |

**Post-tool processing cannot undo completed tool side effects.** See the
[detailed per-integration behavior matrix](https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/AGENT_SUPPORT.md#per-integration-behavior-matrix)
for version-specific prerequisites, protocols, timeouts, failure behavior, and
upstream references. That guide is the source of truth for this summary.

## Guides

| Topic | Documentation |
|-------|---------------|
| Install and verify | [Getting started][getting-started] |
| Configuration and security profiles | [Configuration Guide][configuration] |
| IDE and agent integrations | [Agent Support][agent-support] |
| Scanners | [Scanner Installation][scanners] |
| Console and operations | [Console Guide][console] · [Troubleshooting][troubleshooting] |
| Containers and sandboxes | [Sandbox Guide][sandbox] · [Container Guide][container] |
| Development | [Developer Guide][developer] · [Contributing][contributing] |

## Features

| Feature | Guide |
|---------|-------|
| Secret scanning and custom detection rules | [Secret Scanning][secrets] |
| PII detection | [Secret Scanning][secrets] |
| Prompt injection detection | [Prompt Injection][prompt] |
| Context poisoning detection | [Context Poisoning][context] |
| Image scanning | [Image Scanning][images] |
| Unicode attack detection | [Unicode Attacks][unicode] |
| SSRF protection | [SSRF Protection][ssrf] |
| Config-file and credential exfiltration detection | [Credential Exfiltration][exfiltration] |
| Command credential argument scanning | [Command Credential Scanning][command-credentials] |
| HTTP request credential source scanning | [HTTP Request Credential Scanning][http-credentials] |
| Directory blocking | [Directory Rules][directories] |
| Tool, MCP, and Skill permissions | [Tool Policy][policy] |
| MCP security advisor and scanning | [MCP Server][mcp] |
| Supply-chain scanning | [Configuration Guide][configuration] |
| Sanitize command and secret redaction | [Secret Redaction][redaction] |
| Violation logging | [Violation Logging][violations] |
| Compliance audit logging | [Audit Logging][audit] |
| Support bundles | [Support][support] |
| Uninstall and orphan recovery | [Uninstall Guide][uninstall] |
| Interactive console | [Console Guide][console] |
| Scanner management | [Scanner Installation][scanners] |
| Built-in TOML pattern engine | [TOML Patterns][toml] |
| Secret liveness validation | [Configuration Guide][configuration] |
| Code security scanning | [Scanner Installation][scanners] |
| Pre-commit scanning | [Pre-commit Hook][pre-commit] |
| Inline annotations | [Annotations][annotations] |
| Self-protection | [Security Design][design] |
| Project configuration overlay | [Configuration Guide][configuration] |
| Security instructions | [Configuration Guide][configuration] |
| Multi-agent support and transcript scanning | [Agent Support][agent-support] |
| Agent CLI maturity advisories | [Agent Support][agent-support] |
| OpenCode support | [OpenCode][opencode] |
| Pi and Crush support | [Agent Support][agent-support] |
| Goose host CLI pre-tool enforcement | [Goose Support][goose] |
| Dummy agent for hook testing | [Agent Support][agent-support] |
| Container image | [Container Guide][container] |
| Docker, Podman, and OpenShell sandboxes | [Sandbox Guide][sandbox] |
| OpenShell supervisor middleware | [OpenShell Middleware][openshell] |
| Kubernetes deployment | [Kubernetes Guide][kubernetes] |
| Multi-daemon tray | [Multi-Daemon Tray][tray] |
| Desktop shortcut and autostart | [Multi-Daemon Tray][tray] |
| Tray plugins and event-driven updates | [Multi-Daemon Tray][tray] |
| Hook latency metrics | [Hooks][hooks] |
| OpenTelemetry observability | [Observability][observability] |
| Canary token detection | [Configuration Guide][configuration] |
| Offensive language scanning | [Configuration Guide][configuration] |
| Exfiltration behavior detection | [Credential Exfiltration][exfiltration] |
| Zero-config onboarding | [Configuration Guide][configuration] |
| Language-aware false-positive suppression | [Prompt Injection][prompt] |
| ML prompt injection detection | [Prompt Injection][prompt] |
| LeakTK listen mode | [Scanner Installation][scanners] |
| Scan-and-configure workflow | [Console Guide][console] |
| Security SDK and REST API | [SDK Guide][sdk] |

## License and Contributions

Licensed under [Apache-2.0][license]. Contributions are welcome; see the
[Developer Guide][developer] and [Contributing Guide][contributing].

For production use, install a stable release from PyPI. The `main` branch contains unreleased development code.

<!-- Absolute links also work when docs/index.md includes this README. -->
[docs-index]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/README.md
[docs-export]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/notebooklm-export.md
[design]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/SECURITY_DESIGN.md
[policy]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/TOOL_POLICY.md
[getting-started]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/overview/01-what-is-ai-guardian-install-and-verify.md
[configuration]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/CONFIGURATION.md
[agent-support]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/AGENT_SUPPORT.md
[goose]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/GOOSE.md
[scanners]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/SCANNER_INSTALLATION.md
[console]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/CONSOLE.md
[troubleshooting]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/TROUBLESHOOTING.md
[sandbox]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/Sandbox.md
[container]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/container/README.md
[developer]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/DEVELOPER_GUIDE.md
[contributing]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/CONTRIBUTING.md
[secrets]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/SECRET_SCANNING.md
[prompt]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/PROMPT_INJECTION.md
[context]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/CONTEXT_POISONING.md
[images]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/IMAGE_SCANNING.md
[unicode]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/UNICODE_ATTACKS.md
[ssrf]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/SSRF_PROTECTION.md
[exfiltration]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/CREDENTIAL_EXFILTRATION.md
[command-credentials]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/COMMAND_CREDENTIAL_SCANNING.md
[http-credentials]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/HTTP_REQUEST_CREDENTIAL_SCANNING.md
[directories]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/DIRECTORY_RULES.md
[mcp]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/MCP_SERVER.md
[redaction]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/security/SECRET_REDACTION.md
[violations]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/VIOLATION_LOGGING.md
[audit]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/AUDIT_LOGGING.md
[support]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/SUPPORT.md
[uninstall]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/UNINSTALL.md
[toml]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/TOML_PATTERNS.md
[pre-commit]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/PRE_COMMIT.md
[annotations]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/ANNOTATIONS.md
[opencode]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/OPENCODE.md
[openshell]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/OPENSHELL_MIDDLEWARE.md
[kubernetes]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/kubernetes.md
[tray]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/MULTI_DAEMON_TRAY.md
[hooks]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/HOOKS.md
[observability]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/OBSERVABILITY.md
[sdk]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/docs/SDK.md
[license]: https://github.com/RedHatProductSecurity/ai-guardian/blob/main/LICENSE
