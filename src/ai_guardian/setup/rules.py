"""Rules/guidelines file setup for ai-guardian."""

from pathlib import Path

# Rules/guidelines file locations per IDE
_RULES_IDE_CONFIGS = {
    "junie": {
        "rules_dir": ".junie",
        "rules_file": "guidelines.md",
    },
    "openclaw": {
        "rules_dir": ".",
        "rules_file": "SOUL.md",
    },
    "goose": {
        "rules_dir": ".",
        "rules_file": ".goosehints",
    },
}

_RULES_FILE_CONTENT = """\
# AI Guardian Security Guidelines

You have access to ai-guardian MCP tools. Use them **before acting** to check
security proactively.

## Required Checks

- **Before accessing files** outside the current project or in unfamiliar
  directories, call `check_path` to verify the path is allowed.
- **Before running commands** that contain URLs, credentials, or file paths,
  call `check_command` to verify the command is safe.
- **Before outputting text** that could contain secrets or PII, call
  `sanitize_text` to redact sensitive content.

## When Something Is Blocked

If an operation fails or is flagged, call `get_violations(limit=1)` to
understand the reason. Report the violation type to the user. Do **not**
attempt to work around the block.

## Available MCP Tools

| Tool | Purpose |
|------|---------|
| `check_path` | Verify a file path is allowed before reading/writing |
| `check_command` | Verify a shell command is safe before execution |
| `check_mcp_trust` | Check if an MCP server is trusted |
| `sanitize_text` | Redact secrets and PII from text before output |
| `get_violations` | Get recent security violations and block reasons |
| `get_config` | View current security configuration |
| `scan_directory` | Scan a directory for security issues |
| `doctor` | Check ai-guardian setup health |

## Boundaries

These tools are read-only security advisors. Do not use their results to
circumvent protections. If a path is denied or a command is blocked, that
is the security policy working as intended.
"""


def _handle_rules_setup(
    ide_type: str,
    dry_run: bool = False,
    force: bool = False,
) -> None:
    """Install AI guidelines/rules file for an IDE."""
    rules_config = _RULES_IDE_CONFIGS.get(ide_type)
    if not rules_config:
        print(f"  Rules: IDE '{ide_type}' does not support guidelines files")
        return

    rules_dir = Path(rules_config["rules_dir"])
    if ide_type == "goose":
        # --rules is explicit, but ordinary user setup must still not mutate
        # the current project. Project hints are intentionally user-managed.
        from ai_guardian.goose_support import goose_config_dir

        rules_dir = goose_config_dir()
    rules_path = rules_dir / rules_config["rules_file"]

    if dry_run:
        print(f"  Rules: Would create {rules_path}")
        return

    if rules_path.exists() and not force:
        print(f"  Rules: {rules_path} already exists. Use --force to overwrite.")
        return

    rules_dir.mkdir(parents=True, exist_ok=True)
    with open(rules_path, "w", encoding="utf-8") as f:
        f.write(_RULES_FILE_CONTENT)

    print(f"  Rules: Created {rules_path}")
