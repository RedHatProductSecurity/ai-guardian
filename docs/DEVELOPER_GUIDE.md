# Developer Guide

This guide covers everything you need to contribute to AI Guardian: architecture, development setup, testing, and workflows.

## Architecture Overview

AI Guardian protects AI-assisted coding tools through multiple layers:

```
┌─────────────────────────────────────────────────────┐
│  AI IDE (Claude Code, Cursor, GitHub Copilot, etc.) │
│                                                     │
│  ┌───────────────┐   ┌──────────────────────────┐   │
│  │  PreToolUse   │   │  PostToolUse             │   │
│  │  Hook         │──▶│  Hook                    │   │
│  └───────┬───────┘   └──────────┬───────────────┘   │
└──────────┼──────────────────────┼───────────────────┘
           │                      │
           ▼                      ▼
┌──────────────────────────────────────────────────────┐
│                  AI Guardian                         │
│                                                      │
│  Hooks ──▶ Daemon (optional) ──▶ Scanner engines     │
│                                                      │
│  ┌────────────────────┐  ┌─────────────────────────┐ │
│  │ Detection layers   │  │ Management interfaces   │ │
│  │ • Secret scanning  │  │ • CLI (ai-guardian)      │ │
│  │ • Prompt injection │  │ • Console (TUI)          │ │
│  │ • SSRF protection  │  │ • MCP Server             │ │
│  │ • Directory rules  │  │ • System tray            │ │
│  │ • Tool policy      │  │ • Profiles               │ │
│  │ • Secret redaction │  │                           │ │
│  │ • Unicode attacks  │  │                           │ │
│  │ • Config exfil     │  │                           │ │
│  │ • PII detection    │  │                           │ │
│  └────────────────────┘  └─────────────────────────┘ │
└──────────────────────────────────────────────────────┘
```

### Key Components

| Component | Path | Purpose |
|-----------|------|---------|
| Hooks entry point | `src/ai_guardian/__init__.py` | PreToolUse / PostToolUse hook handlers |
| CLI | `src/ai_guardian/cli.py` | Command-line interface |
| Daemon | `src/ai_guardian/daemon/` | Background service for faster hook responses |
| Console (TUI) | `src/ai_guardian/tui/` | Interactive terminal UI for configuration |
| MCP Server | `src/ai_guardian/mcp/` | MCP security advisor tools |
| Scanner engines | `src/ai_guardian/scanners/` | Multi-engine secret scanning (gitleaks, betterleaks, leaktk) |
| Custom Scanner SDK | `src/ai_guardian/scanners/sdk.py` | Python-based scanner base class |
| Prompt injection | `src/ai_guardian/scanners/prompt_injection.py` | Heuristic prompt injection detection |
| SSRF protection | `src/ai_guardian/scanners/ssrf.py` | Private IP / metadata endpoint blocking |
| Tool policy | `src/ai_guardian/tools/policy.py` | Allow/deny lists for tools and skills |
| Profiles | `src/ai_guardian/profile_manager.py` | Named configuration profiles |
| Annotations | `src/ai_guardian/annotations.py` | Inline false-positive suppression |
| Violation logging | `src/ai_guardian/violations/logger.py` | JSON audit trail |
| System tray | `src/ai_guardian/tray/` | macOS/Linux menu bar icon |

## Development Setup

### Prerequisites

- Python 3.10, 3.11, or 3.12
- Git
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Install for Development

```bash
# Clone your fork
gh repo fork RedHatProductSecurity/ai-guardian --clone
cd ai-guardian

# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Or using uv
uv pip install -e ".[dev]"
```

### Keep Your Fork in Sync

```bash
git remote add upstream https://github.com/RedHatProductSecurity/ai-guardian.git
git fetch upstream
git checkout main && git merge upstream/main
```

## Working with AI Guardian Source Code

### Self-Protection and Blocked Files

AI Guardian protects itself. When you have it installed and active, it may block reads of certain files in this repository -- **this is expected behavior**.

**Files that may be blocked:**
- `tests/test_prompt_injection.py` -- contains actual attack patterns for testing
- `src/ai_guardian/prompt_injection.py` -- contains detection patterns
- Other test files with injection test cases

**Solutions for local development:**

1. **Temporarily disable prompt injection detection:**
   ```json
   // ~/.config/ai-guardian/ai-guardian.json
   { "prompt_injection": { "enabled": false } }
   ```

2. **Add an allowlist pattern** (use with caution):
   ```json
   {
     "prompt_injection": {
       "allowlist_patterns": [".*/ai-guardian/.*"]
     }
   }
   ```

3. **Lower sensitivity:**
   ```json
   { "prompt_injection": { "sensitivity": "low" } }
   ```

### AI-Assisted Development

You can use Claude or other AI assistants to edit source code, tests, documentation, and configuration. The following files remain protected regardless:

- `~/.config/ai-guardian/ai-guardian.json` (user config)
- `~/.claude/settings.json` (IDE hooks)
- `~/.cache/ai-guardian/*` (cache files)
- `.ai-read-deny` marker files
- pip-installed `site-packages/ai_guardian/*`

## Testing

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=ai_guardian --cov-report=term-missing

# Run specific category
pytest tests/unit/         # Fast, isolated (~1,141 tests)
pytest tests/integration/  # Cross-component (~82 tests)
pytest tests/ux/           # User experience contracts (~5 tests)

# Run specific file
pytest tests/unit/test_specific.py -v
```

Or using uv:

```bash
uv run --extra dev python -m pytest
```

### Test Structure

```
tests/
├── unit/           # Single-component tests (fast, mocked dependencies)
├── integration/    # Multi-component tests (may use real files/subprocess)
├── ux/             # User-facing behavior validation
├── fixtures/       # Shared test data and mock utilities
│   ├── attack_constants.py   # Fake test credentials
│   └── mock_mcp_server.py    # MCP hook data helpers
└── conftest.py     # Shared pytest fixtures
```

### Writing Tests

**Unit tests** (`tests/unit/`): Test single components in isolation. Mock external dependencies. No file I/O, network calls, or subprocess.

**Integration tests** (`tests/integration/`): Test multiple components together. May use real files, subprocess, or external tools.

**UX contract tests** (`tests/ux/`): Validate user-facing behavior -- CLI output, error messages, permission flow.

### UX Contract Tests

When adding or modifying security features that affect what users see, create UX contract tests:

```python
@patch('ai_guardian._load_secret_scanning_config')
@patch('ai_guardian._load_pattern_server_config')
def test_user_experience_feature_name(self, mock_pattern_config, mock_scan_config):
    """
    USER EXPERIENCE: [Brief description] -> [Expected outcome]

    Scenario:
    1. User asks Claude: "[Example user request]"
    2. Claude tries to [action]
    3. ai-guardian [hook] runs
    4. [Threat/condition detected]

    Expected User Experience:
    X/OK [What happens]
    User sees: "[Exact message]"
    """
    mock_pattern_config.return_value = None
    mock_scan_config.return_value = ({"enabled": True}, None)
    # Test implementation...
```

**Test isolation**: UX tests must NOT use the user's `~/.config/ai-guardian/ai-guardian.json`. Mock all `_load_*_config()` functions.

### Adding Integration Tests for MCP Tools

1. Add attack constants to `tests/fixtures/attack_constants.py`
2. Use `tests/fixtures/mock_mcp_server.py` for hook data
3. Create test file in `tests/integration/`

```python
from tests.fixtures.mock_mcp_server import create_hook_data

hook_data = create_hook_data(
    tool_name="mcp__notebooklm-mcp__notebook_create",
    tool_input={"title": "Test Notebook"}
)
```

### Test Coverage

- Target: >70% code coverage
- Run coverage reports before submitting PRs
- Add tests for all new features and bug fixes

## New Feature Checklist

When adding a new feature, check whether it needs any of these surfaces:

| Surface | When to add | Location |
|---------|-------------|----------|
| MCP tool | Read-only/query operation AI would benefit from calling | `src/ai_guardian/mcp/` |
| Console panel | Feature has configurable settings | `src/ai_guardian/tui/` |
| System tray | Feature produces a quick status or count | `src/ai_guardian/tray/` |
| CLI command | Feature needs a standalone command | `src/ai_guardian/cli.py` |

### Configuration Schema Changes

When adding new configuration options, update all of these:

1. **JSON Schema**: `src/ai_guardian/schemas/ai-guardian-config.schema.json`
2. **Setup defaults**: `src/ai_guardian/setup/config.py` (`_create_default_config()`)
3. **Example config**: `ai-guardian-example.json`
4. **Console**: Verify auto-generation from schema (most panels auto-generate)
5. **Code**: Implement reading the new config
6. **Tests**: Cover the new options
7. **Documentation**: Update relevant `docs/` file and CHANGELOG.md
8. **Verify**: Run `ai-guardian setup --create-config` to confirm output

## Code Quality

### Linting (Optional but Recommended)

```bash
black --check ai_guardian/ tests/   # Formatting
pylint ai_guardian/                  # Static analysis
ruff check ai_guardian/ tests/      # Fast linting
```

### Pre-Commit Checks

**For code changes:**
1. Run tests: `pytest`
2. Check coverage: `pytest --cov=ai_guardian`
3. Update CHANGELOG.md under `[Unreleased]`

**For documentation-only changes:**
1. Update CHANGELOG.md if the change is notable
2. Tests are not required

## Security Model for Contributors

### Standard Open-Source Workflow

1. You edit code with AI assistance in your local fork
2. Submit a pull request
3. Maintainers review (looking for backdoors, vulnerabilities)
4. CI/CD tests run automatically
5. Community review on the public PR
6. Maintainer merges after approval

Pip-installed ai-guardian on users' systems stays protected even if malicious code appears in a PR.

### What's Protected

- Config files and IDE hooks are always protected, even for maintainers
- This defense-in-depth approach prevents accidental security bypasses
- See [SECURITY_DESIGN.md](SECURITY_DESIGN.md) for architecture details

## CI/CD

### GitHub Actions Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| Tests | Push to main, PRs | Python 3.9-3.12, coverage to Codecov |
| Lint | PRs | pylint, black, ruff |
| Publish | Version tags (`v*`) | Build, publish to PyPI, create GitHub Release |
| Integration Tests | Daily 2 AM UTC, PRs | Scanner version checks, MCP integration, test isolation |

### Dependabot

- GitHub Actions: monthly updates, grouped PRs
- Python packages: monthly updates, grouped PRs
- See `.github/dependabot.yml` for configuration

## Project Structure

```
ai-guardian/
├── src/ai_guardian/         # Main package
│   ├── config/              # Configuration loading, writing, display
│   ├── daemon/              # Background daemon service
│   ├── hook_adapters/       # IDE-specific hook adapters
│   ├── hook_events/         # Per-event hook handlers
│   ├── mcp/                 # MCP security advisor server
│   ├── patterns/            # Detection patterns and validators
│   ├── reporting/           # Audit, metrics, SARIF, support bundles
│   ├── scanners/            # Multi-engine scanner framework + SDK
│   ├── schemas/             # JSON config schema
│   ├── setup/               # IDE hook setup and config creation
│   ├── templates/           # Config templates
│   ├── tools/               # Tool policy and patterns
│   ├── tray/                # macOS/Linux system tray
│   ├── tui/                 # Interactive Console (Textual)
│   ├── violations/          # Violation tracking and guidance
│   └── web/                 # Web console (NiceGUI)
├── tests/
│   ├── unit/                # Fast isolated tests
│   ├── integration/         # Cross-component tests
│   ├── ux/                  # UX contract tests
│   └── fixtures/            # Test data and helpers
├── docs/                    # Detailed documentation
│   └── security/            # Security feature docs
├── .github/
│   └── workflows/           # CI/CD pipelines
├── pyproject.toml           # Package metadata
├── CHANGELOG.md             # Version history
├── RELEASING.md             # Release procedures
└── ai-guardian-example.json # Example configuration
```

## Further Reading

- [Configuration Guide](CONFIGURATION.md)
- [Security Design](SECURITY_DESIGN.md)
- [Tool Policy](TOOL_POLICY.md)
- [MCP Server](MCP_SERVER.md)
- [Console Guide](CONSOLE.md)
- [Annotations](ANNOTATIONS.md)
- [Releasing](../RELEASING.md)
- [Agent Instructions](../AGENTS.md) -- detailed coding guidelines and patterns
