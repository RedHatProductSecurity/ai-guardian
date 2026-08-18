# AI Guardian Documentation

This directory contains detailed documentation for AI Guardian. The main [README.md](../README.md) provides a quick overview; these docs cover configuration, features, and architecture in depth.

## Getting Started

| Document | Description |
|----------|-------------|
| [Configuration Guide](CONFIGURATION.md) | Config file locations, options, precedence, and remote configs |
| [Configuration Cookbook](COOKBOOK.md) | Practical Q&A pairs for common configuration tasks |
| [Scanner Installation](SCANNER_INSTALLATION.md) | Install and manage gitleaks, betterleaks, leaktk |
| [TOML Pattern Engine](TOML_PATTERNS.md) | Built-in Python scanner with 267 pre-compiled TOML patterns |
| [Console Guide](CONSOLE.md) | Interactive TUI for managing configuration |
| [Hook Ordering](HOOKS.md) | How hooks work and ordering requirements |
| [Troubleshooting](TROUBLESHOOTING.md) | Daemon, tray, and container issue resolution |

## Security Features

| Document | Description |
|----------|-------------|
| [Security Overview](security/) | Index of all security feature documentation |
| [Secret Scanning](security/SECRET_SCANNING.md) | Secret detection, pattern server, false positives |
| [Prompt Injection](security/PROMPT_INJECTION.md) | Heuristic detection, sensitivity, allowlists |
| [SSRF Protection](security/SSRF_PROTECTION.md) | Private IP blocking, metadata endpoints, limitations |
| [Unicode Attacks](security/UNICODE_ATTACKS.md) | Zero-width chars, bidi override, homoglyphs |
| [Directory Rules](security/DIRECTORY_RULES.md) | `.ai-read-deny` markers and config-based rules |
| [Credential Exfiltration](security/CREDENTIAL_EXFILTRATION.md) | Config file scanning for exfiltration patterns |
| [Secret Redaction](security/SECRET_REDACTION.md) | Masking secrets in tool outputs |
| [Image Scanning (OCR)](security/IMAGE_SCANNING.md) | OCR-based secret/PII detection in images, IDE limitations |
| [Inline Annotations](ANNOTATIONS.md) | Suppress false positives with per-line or block annotations |

## Observability

| Document | Description |
|----------|-------------|
| [Observability Guide](OBSERVABILITY.md) | OTEL export, Grafana integration, span hierarchy, CLI trace export |

## Architecture & Policy

| Document | Description |
|----------|-------------|
| [Security Design](SECURITY_DESIGN.md) | Architecture principles, self-protection, known limitations |
| [Tool Policy](TOOL_POLICY.md) | Allow/deny lists for Skills, MCP, Bash, Write |
| [Permissions Comparison](PERMISSIONS_COMPARISON.md) | ai-guardian vs settings.json permissions |
| [Violation Logging](VIOLATION_LOGGING.md) | JSON audit trail of blocked operations |

## AI Security Awareness

| Document | Description |
|----------|-------------|
| [MCP Server](MCP_SERVER.md) | MCP security advisor server — tools, setup, proactive levels, support bundles |
| [MCP Security Scanning](MCP_SERVER.md#mcp-security-scanning) | Audit MCP server configs and source code for credential exposure, supply chain risks |
| [Multi-Daemon Tray](MULTI_DAEMON_TRAY.md) | Discover and manage daemons across local, Podman/Docker, and Kubernetes |

## IDE Integration

| Document | Description |
|----------|-------------|
| [Agent Support](AGENT_SUPPORT.md) | Multi-agent hook adapters — capability matrix, setup, and architecture |
| [Pre-commit Hook](PRE_COMMIT.md) | Scan staged files for secrets before commit |
| [GitHub Copilot Setup](GITHUB_COPILOT.md) | Setup guide for GitHub Copilot |
| [Aider Setup](AIDER.md) | Git hook integration for Aider |
| [AiderDesk Setup](AIDERDESK.md) | Setup guide for AiderDesk |
| [Multi-Engine Support](MULTI_ENGINE_SUPPORT.md) | Scanner engine options and future plans |
| [Pattern Server](PATTERN_SERVER.md) | Enterprise pattern server configuration |

## Container

| Document | Description |
|----------|-------------|
| [Container Image](../container/README.md) | UBI-based image with all headless IDEs, published to quay.io |

## Development

| Document | Description |
|----------|-------------|
| [Developer Guide](DEVELOPER_GUIDE.md) | Architecture, setup, testing, and development workflows |
| [Contributing](../CONTRIBUTING.md) | Fork workflow, PR guidelines |
| [Agent Instructions](../AGENTS.md) | Development guidelines, testing, CI/CD |
| [Releasing](../RELEASING.md) | Release process and version management |
| [Changelog](../CHANGELOG.md) | Version history |

