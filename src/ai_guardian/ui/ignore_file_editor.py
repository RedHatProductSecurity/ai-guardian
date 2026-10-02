"""Shared logic for the 'Ignore File...' flow.

Constants, helpers, and validation for adding paths to .aiguardignore.toml.
Used by ask dialog (all tiers), violations page, and directory scan page.
"""

from typing import List, Optional, Tuple

SCOPE_THIS_SCANNER = "this_scanner"
SCOPE_ALL_SCANNERS = "all_scanners"
SCOPE_SELECT_SCANNERS = "select_scanners"

SCOPE_LABELS = {
    SCOPE_THIS_SCANNER: "This scanner only",
    SCOPE_ALL_SCANNERS: "All scanners",
    SCOPE_SELECT_SCANNERS: "Select scanners...",
}

SCANNER_LABELS = {
    "secret_scanning": "Secret Scanning",
    "scan_pii": "PII Scanning",
    "prompt_injection": "Prompt Injection",
    "config_file_scanning": "Config File Scanning",
    "context_poisoning": "Context Poisoning",
    "supply_chain": "Supply Chain",
    "image_scanning": "Image Scanning",
}

_IGNORE_FILE_TYPES = frozenset(
    {
        "secret_detected",
        "pii_detected",
        "prompt_injection",
        "jailbreak_detected",
        "config_file_exfil",
        "context_poisoning",
        "supply_chain",
        "image_secret_detected",
        "image_pii_detected",
    }
)


def resolve_scanner_types(
    scope: str,
    current_scanner: str,
    selected_scanners: Optional[List[str]] = None,
) -> Optional[List[str]]:
    """Resolve scope choice to scanner type list. None means global allowlist."""
    if scope == SCOPE_ALL_SCANNERS:
        return None
    if scope == SCOPE_SELECT_SCANNERS and selected_scanners:
        return selected_scanners
    return [current_scanner]


def validate_ignore_path(path: str) -> Tuple[bool, str]:
    """Validate that an ignore path is safe."""
    if not path or not path.strip():
        return False, "Path is empty"
    path = path.strip()
    if ".." in path.split("/"):
        return False, "Path contains '..' traversal"
    if path in ("**", "*", "**/*"):
        return False, "Pattern too broad — would disable scanning entirely"
    return True, "Path is valid"


def suggest_ignore_path(file_path: str) -> str:
    """Suggest a relative path for the ignore file entry."""
    from ai_guardian.aiguardignore import make_relative_path

    return make_relative_path(file_path)


def get_project_root_for_file(file_path: str):
    """Get the project root for a violation file path."""
    from ai_guardian.aiguardignore import find_project_root_for_file

    return find_project_root_for_file(file_path)
