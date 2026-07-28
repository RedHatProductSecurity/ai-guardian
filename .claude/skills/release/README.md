# Release Skill

This skill automates the release management workflow for any project using semantic versioning. Works with Python, Node.js, and other project types through automatic version file detection.

## Features

- **Auto-detection**: Automatically finds version files (pyproject.toml, package.json, __init__.py, etc.)
- **Project-agnostic**: Works with Python, Node.js, and generic projects
- **Multi-file sync**: Keeps all version files synchronized
- **Smart configuration**: Saves detected files to `.release-config.json` for future use
- **Semantic versioning**: Follows semver with -dev and -test suffixes
- **CHANGELOG automation**: Updates CHANGELOG.md following Keep a Changelog format

## Location

This skill can be placed in:
- **Project-specific**: `.claude/skills/release/` (version controlled with your project)
- **Global**: `~/.claude/skills/release/` (available across all projects)

Project-specific installation is recommended for:
- ✅ Version controlling the skill with your project
- ✅ Customizing for project-specific workflows
- ✅ Testing in CI/CD
- ✅ Sharing with contributors

## Files

- **SKILL.md** - Skill documentation (invoked by Claude Code)
- **release_helper.py** - Python automation utilities (ai-guardian specific)
- **README.md** - This file
- **EXAMPLE_USAGE.md** - Usage examples and troubleshooting

## Usage

In Claude Code, invoke the skill with:

```bash
/release minor              # Create minor version release (1.1.0 -> 1.2.0)
/release patch              # Create patch version release (1.1.0 -> 1.1.1)
/release major              # Create major version release (1.0.0 -> 2.0.0)
/release hotfix v1.1.0      # Create hotfix from v1.1.0 tag
/release test               # Create TestPyPI test release
```

## Helper Script

The `release_helper.py` script can also be used standalone:

```bash
# Get current version (auto-detects version files on first run)
python .claude/skills/release/release_helper.py get-version
# Output:
# 🔍 Auto-detecting version files...
#   ✓ Found: pyproject.toml (version: 1.2.0-dev)
#   ✓ Found: src/myproject/__init__.py (version: 1.2.0-dev)
# ✓ Saved configuration to .release-config.json
# Current version: 1.2.0-dev

# Calculate next version
python .claude/skills/release/release_helper.py calc-version "1.2.0-dev" minor
# Output: 1.3.0

# Update version in all detected files
python .claude/skills/release/release_helper.py update-version "1.2.0"

# Update CHANGELOG.md
python .claude/skills/release/release_helper.py update-changelog "1.2.0" --date "2026-04-08"

# Validate prerequisites
python .claude/skills/release/release_helper.py validate --type regular
```

## Testing

Tests are located in the AI Guardian repository:

```bash
cd /path/to/ai-guardian
pytest tests/test_release_helper.py -v
```

## Requirements

- Python 3.9+
- Access to the AI Guardian repository
- Git command line tools

## Workflow

When you invoke `/release <type>`, Claude Code will:

1. Load SKILL.md and provide it as context
2. Follow the documented workflow in SKILL.md
3. Use release_helper.py to automate version updates
4. Guide you through git operations
5. Provide post-release checklist

## Version Management

The skill automatically detects and manages version files in your project:

**Supported patterns**:
- Python: `pyproject.toml`, `setup.py`, `__init__.py`
- Node.js: `package.json`
- Generic: `VERSION`, `version.txt`

**Configuration**: On first use, detected files are saved to `.release-config.json`:
```json
{
  "version_files": [
    {
      "path": "pyproject.toml",
      "pattern": "version = \"{version}\"",
      "description": "Python project metadata"
    }
  ],
  "changelog": "CHANGELOG.md"
}
```

The helper script ensures all configured files are updated atomically, maintaining version consistency.

## Safety Features

- Validates prerequisites before starting
- Checks versions match between files
- Verifies CHANGELOG.md has content before release
- Provides clear error messages
- Fail-safe: manual recovery instructions

## Documentation

- **SKILL.md** - Complete skill documentation and workflow
- **.release-config.json** - Auto-generated configuration (can be edited manually)
- **RELEASING.md** (if available) - Project-specific release procedures
- **AGENTS.md** (if available) - Project-specific guidelines

## Compatibility

- **Python projects**: pyproject.toml, setup.py, __init__.py
- **Node.js projects**: package.json
- **Generic projects**: VERSION, version.txt
- **Custom patterns**: Edit `.release-config.json` to add your own

## Support

For issues or questions about this skill:
- Original implementation: https://github.com/RedHatProductSecurity/ai-guardian/issues/16
- Adaptable for any project with version files
