"""Shared fix-guidance logic for violation resolution instructions.

This module is the single source of truth for the config snippets and
instructions shown to users in the TUI Console, Web Console, and CLI.

IMPORTANT — self-protection rule (see AGENTS.md):
  These instructions must ONLY appear in user-facing channels.
  They must NEVER be returned via MCP tool responses or hook messages.
"""

import json
from typing import Tuple

from ai_guardian.violations.utils import is_temp_path


def _type_placeholders(types: list) -> list:
    """Build per-type regex placeholder strings from a list of type names."""
    if not types:
        return ["<regex>"]
    return [f"<regex-for-{t}>" for t in types]


def _temp_file_notice(section: str, key: str) -> str:
    """Build the instructions text for a violation detected in a temp file."""
    verb = "pattern" if key == "allowlist_patterns" else "file"
    return f"Detection in temporary file. Add {verb} to {section}.{key}:"


def get_resolution_instructions(violation: dict) -> Tuple[str, str]:
    """Return (instructions_text, config_snippet) for a violation type.

    instructions_text is plain text (no Rich markup) so it works in TUI,
    Web, and CLI.  Callers can wrap with Rich/HTML formatting as needed.

    Returns ("", "") for unknown violation types.
    """
    vtype = violation.get("violation_type", "")
    blocked = violation.get("blocked", {})
    if not isinstance(blocked, dict):
        blocked = {}
    suggestion = violation.get("suggestion", {})
    if not isinstance(suggestion, dict):
        suggestion = {}

    if vtype == "tool_permission":
        rule = suggestion.get("rule", {})
        snippet = (
            json.dumps({"permissions": {"rules": [rule]}}, indent=2) if rule else ""
        )
        return "Add this rule to permissions.rules in ai-guardian.json:", snippet

    if vtype == "prompt_injection":
        file_path = blocked.get("file_path")
        if is_temp_path(file_path):
            return _temp_file_notice("prompt_injection", "allowlist_patterns"), ""
        pattern = blocked.get("pattern", "<pattern>")
        snippet = json.dumps(
            {"prompt_injection": {"allowlist_patterns": [pattern]}}, indent=2
        )
        return "Add this pattern to prompt_injection.allowlist_patterns:", snippet

    if vtype == "jailbreak_detected":
        file_path = blocked.get("file_path")
        if is_temp_path(file_path):
            return _temp_file_notice("prompt_injection", "allowlist_patterns"), ""
        pattern = blocked.get("pattern", blocked.get("matched_text", "<pattern>"))
        snippet = json.dumps(
            {"prompt_injection": {"allowlist_patterns": [pattern]}}, indent=2
        )
        return "Add this pattern to prompt_injection.allowlist_patterns:", snippet

    if vtype == "secret_detected":
        file_path = blocked.get("file_path")
        secret_type = blocked.get("rule_id", blocked.get("secret_type", "unknown"))
        placeholder = (
            f"<regex-for-{secret_type}>" if secret_type != "unknown" else "<regex>"
        )
        if is_temp_path(file_path):
            snippet = json.dumps(
                {"secret_scanning": {"allowlist_patterns": [placeholder]}}, indent=2
            )
            return (
                _temp_file_notice("secret_scanning", "allowlist_patterns"),
                snippet,
            )
        from ai_guardian.scanners.secret_types import get_secret_type_display

        instructions = (
            f"Secret type: {get_secret_type_display(secret_type)}\n\n"
            "Option 1: Add a regex pattern to ai-guardian.json:\n"
            f'  "secret_scanning": {{"allowlist_patterns": ["{placeholder}"]}}\n\n'
            "Option 2: Add inline comment at the end of the line:\n"
            "  YOUR_SECRET_LINE # gitleaks:allow\n\n"
            "Option 3: Add to .gitleaks.toml allowlist\n\n"
            "Tip: Option 1 works for both file scanning and tool output scanning.\n"
            "Options 2-3 only work for file scanning (PreToolUse)."
        )
        snippet = json.dumps(
            {"secret_scanning": {"allowlist_patterns": [placeholder]}}, indent=2
        )
        return instructions, snippet

    if vtype == "directory_blocking":
        denied_dir = blocked.get("denied_directory", "<directory>")
        instructions = (
            "Add an allow rule to directory_rules.rules or remove the deny pattern.\n\n"
            f"To remove the deny file:\n  rm {denied_dir}/.ai-read-deny"
        )
        snippet = f"rm {denied_dir}/.ai-read-deny"
        return instructions, snippet

    if vtype == "pii_detected":
        file_path = blocked.get("file_path")
        if is_temp_path(file_path):
            return _temp_file_notice("scan_pii", "allowlist_patterns"), ""
        pii_types = blocked.get("pii_types", [])
        placeholders = _type_placeholders(pii_types)
        cfg = {
            "scan_pii": {
                "allowlist_patterns": placeholders,
                "ignore_files": [file_path or "<file>"],
            }
        }
        snippet = json.dumps(cfg, indent=2)
        return (
            "Add pattern to scan_pii.allowlist_patterns or file to scan_pii.ignore_files:",
            snippet,
        )

    if vtype == "secret_redaction":
        redacted_types = blocked.get("redacted_types", [])
        placeholders = _type_placeholders(redacted_types)
        snippet = json.dumps(
            {"secret_scanning": {"allowlist_patterns": placeholders}}, indent=2
        )
        return "Add pattern to secret_scanning.allowlist_patterns:", snippet

    if vtype == "ssrf_blocked":
        tool_value = blocked.get("tool_value", "")
        domain = "<domain>"
        if tool_value:
            try:
                from urllib.parse import urlparse

                parsed = urlparse(tool_value)
                if parsed.hostname:
                    domain = parsed.hostname
            except Exception:
                pass  # intentionally silent — optional dependency
        snippet = json.dumps(
            {"ssrf_protection": {"additional_allowed_domains": [domain]}}, indent=2
        )
        return "Add domain to ssrf_protection.additional_allowed_domains:", snippet

    if vtype == "config_file_exfil":
        file_path = blocked.get("file_path")
        if is_temp_path(file_path):
            return _temp_file_notice("config_file_scanning", "ignore_files"), ""
        snippet = json.dumps(
            {"config_file_scanning": {"ignore_files": [file_path or "<file>"]}},
            indent=2,
        )
        return "Add file to config_file_scanning.ignore_files:", snippet

    if vtype == "secret_in_transcript":
        secret_type = blocked.get("secret_type", "")
        if secret_type:
            placeholder = f"<regex-for-{secret_type}>"
        else:
            placeholder = "<regex>"
        snippet = json.dumps(
            {"secret_scanning": {"allowlist_patterns": [placeholder]}}, indent=2
        )
        instructions = (
            "Secret found in transcript from '!' shell command.\n"
            "Add pattern to secret_scanning.allowlist_patterns "
            "or avoid using '!' to display secrets:"
        )
        return instructions, snippet

    if vtype == "pii_in_transcript":
        pii_types = blocked.get("pii_types", [])
        placeholders = _type_placeholders(pii_types)
        snippet = json.dumps(
            {"scan_pii": {"allowlist_patterns": placeholders}}, indent=2
        )
        instructions = (
            "PII found in transcript from '!' shell command.\n"
            "Add pattern to scan_pii.allowlist_patterns:"
        )
        return instructions, snippet

    if vtype in ("image_secret_detected", "image_pii_detected"):
        file_path = blocked.get("file_path")
        if is_temp_path(file_path):
            return _temp_file_notice("image_scanning", "ignore_files"), ""
        snippet = json.dumps(
            {"image_scanning": {"ignore_files": [file_path or "<file>"]}}, indent=2
        )
        return "Add file to image_scanning.ignore_files:", snippet

    return "Review the violation details and update config as needed.", ""
