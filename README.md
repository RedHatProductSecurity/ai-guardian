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
- [Source documentation index](docs/README.md) — browse the documentation in this repository.
- [Ask questions about the documentation in NotebookLM](https://notebook.google.com/notebook/9b78ebca-d327-4df7-8f2e-64e518f2ddcb) — a Google account is required.
- [Use the combined documentation export with a private LLM tool](docs/notebooklm-export.md) — upload this generated single-file compilation to your organization's approved private NotebookLM instance or other LLM search tool. It is generated during releases; do not edit it directly.

## Security Disclaimer

**AI Guardian is one layer of defense in depth, not a guarantee against every
threat.** Detection may miss novel or obfuscated attacks, and secret coverage
depends on available scanner patterns. By design, scanner errors fail open so
development remains available. Combine AI Guardian with code review, CI/CD
scanning, network controls, and secret management. See [Security Design](docs/SECURITY_DESIGN.md)
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
> Write, Edit) are allowed and scanned by hooks. See [Tool Policy](docs/TOOL_POLICY.md)
> for the security posture and configuration.

## Guides

| Topic | Documentation |
|-------|---------------|
| Install and verify | [Getting started](docs/overview/01-what-is-ai-guardian-install-and-verify.md) |
| Configuration and security profiles | [Configuration Guide](docs/CONFIGURATION.md) |
| IDE and agent integrations | [Agent Support](docs/AGENT_SUPPORT.md) |
| Scanners | [Scanner Installation](docs/SCANNER_INSTALLATION.md) |
| Console and operations | [Console Guide](docs/CONSOLE.md) · [Troubleshooting](docs/TROUBLESHOOTING.md) |
| Containers and sandboxes | [Sandbox Guide](docs/Sandbox.md) · [Container Guide](container/README.md) |
| Development | [Developer Guide](docs/DEVELOPER_GUIDE.md) · [Contributing](CONTRIBUTING.md) |

## Features

| Feature | Guide |
|---------|-------|
| Secret scanning and custom detection rules | [Secret Scanning](docs/security/SECRET_SCANNING.md) |
| PII detection | [Secret Scanning](docs/security/SECRET_SCANNING.md) |
| Prompt injection detection | [Prompt Injection](docs/security/PROMPT_INJECTION.md) |
| Context poisoning detection | [Context Poisoning](docs/security/CONTEXT_POISONING.md) |
| Image scanning | [Image Scanning](docs/security/IMAGE_SCANNING.md) |
| Unicode attack detection | [Unicode Attacks](docs/security/UNICODE_ATTACKS.md) |
| SSRF protection | [SSRF Protection](docs/security/SSRF_PROTECTION.md) |
| Config-file and credential exfiltration detection | [Credential Exfiltration](docs/security/CREDENTIAL_EXFILTRATION.md) |
| Command credential argument scanning | [Command Credential Scanning](docs/security/COMMAND_CREDENTIAL_SCANNING.md) |
| Directory blocking | [Directory Rules](docs/security/DIRECTORY_RULES.md) |
| Tool, MCP, and Skill permissions | [Tool Policy](docs/TOOL_POLICY.md) |
| MCP security advisor and scanning | [MCP Server](docs/MCP_SERVER.md) |
| Supply-chain scanning | [Configuration Guide](docs/CONFIGURATION.md) |
| Sanitize command and secret redaction | [Secret Redaction](docs/security/SECRET_REDACTION.md) |
| Violation logging | [Violation Logging](docs/VIOLATION_LOGGING.md) |
| Compliance audit logging | [Audit Logging](docs/AUDIT_LOGGING.md) |
| Support bundles | [Support](docs/SUPPORT.md) |
| Uninstall and orphan recovery | [Uninstall Guide](docs/UNINSTALL.md) |
| Interactive console | [Console Guide](docs/CONSOLE.md) |
| Scanner management | [Scanner Installation](docs/SCANNER_INSTALLATION.md) |
| Built-in TOML pattern engine | [TOML Patterns](docs/TOML_PATTERNS.md) |
| Secret liveness validation | [Configuration Guide](docs/CONFIGURATION.md) |
| Code security scanning | [Scanner Installation](docs/SCANNER_INSTALLATION.md) |
| Pre-commit scanning | [Pre-commit Hook](docs/PRE_COMMIT.md) |
| Inline annotations | [Annotations](docs/ANNOTATIONS.md) |
| Self-protection | [Security Design](docs/SECURITY_DESIGN.md) |
| Project configuration overlay | [Configuration Guide](docs/CONFIGURATION.md) |
| Security instructions | [Configuration Guide](docs/CONFIGURATION.md) |
| Multi-agent support and transcript scanning | [Agent Support](docs/AGENT_SUPPORT.md) |
| Agent CLI maturity advisories | [Agent Support](docs/AGENT_SUPPORT.md) |
| OpenCode support | [OpenCode](docs/OPENCODE.md) |
| Pi and Crush support | [Agent Support](docs/AGENT_SUPPORT.md) |
| Dummy agent for hook testing | [Agent Support](docs/AGENT_SUPPORT.md) |
| Container image | [Container Guide](container/README.md) |
| Docker, Podman, and OpenShell sandboxes | [Sandbox Guide](docs/Sandbox.md) |
| OpenShell supervisor middleware | [OpenShell Middleware](docs/OPENSHELL_MIDDLEWARE.md) |
| Kubernetes deployment | [Kubernetes Guide](docs/kubernetes.md) |
| Multi-daemon tray | [Multi-Daemon Tray](docs/MULTI_DAEMON_TRAY.md) |
| Desktop shortcut and autostart | [Multi-Daemon Tray](docs/MULTI_DAEMON_TRAY.md) |
| Tray plugins and event-driven updates | [Multi-Daemon Tray](docs/MULTI_DAEMON_TRAY.md) |
| Hook latency metrics | [Hooks](docs/HOOKS.md) |
| OpenTelemetry observability | [Observability](docs/OBSERVABILITY.md) |
| Canary token detection | [Configuration Guide](docs/CONFIGURATION.md) |
| Offensive language scanning | [Configuration Guide](docs/CONFIGURATION.md) |
| Exfiltration behavior detection | [Credential Exfiltration](docs/security/CREDENTIAL_EXFILTRATION.md) |
| Zero-config onboarding | [Configuration Guide](docs/CONFIGURATION.md) |
| Language-aware false-positive suppression | [Prompt Injection](docs/security/PROMPT_INJECTION.md) |
| ML prompt injection detection | [Prompt Injection](docs/security/PROMPT_INJECTION.md) |
| LeakTK listen mode | [Scanner Installation](docs/SCANNER_INSTALLATION.md) |
| Scan-and-configure workflow | [Console Guide](docs/CONSOLE.md) |
| Security SDK and REST API | [SDK Guide](docs/SDK.md) |

## License and Contributions

Licensed under [Apache-2.0](LICENSE). Contributions are welcome; see the
[Developer Guide](docs/DEVELOPER_GUIDE.md) and [Contributing Guide](CONTRIBUTING.md).

For production use, install a stable release from PyPI. The `main` branch contains unreleased development code.
