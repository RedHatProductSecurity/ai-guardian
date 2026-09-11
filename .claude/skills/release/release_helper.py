#!/usr/bin/env python3
"""
Project-Agnostic Release Helper

This module provides automation utilities for release management:
- Auto-detects version files in your project
- Supports multiple project types (Python, Node.js, etc.)
- Updates CHANGELOG.md with proper formatting
- Validates version consistency
- Calculates next version based on release type
- Reports the versioned normal and OpenShell container image references

Supports optional .release-config.json for custom configurations.
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Tuple, Optional, List, Dict, Any


NORMAL_CONTAINER_REPOSITORY = "quay.io/redhatproductsecurity/ai-guardian"
OPENSHELL_CONTAINER_REPOSITORY = (
    "quay.io/redhatproductsecurity/ai-guardian-openshell"
)


def get_container_image_references(version: str) -> Dict[str, str]:
    """Return the versioned normal and OpenShell container image references."""
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError(f"Invalid release version for container images: {version}")

    return {
        "normal": f"{NORMAL_CONTAINER_REPOSITORY}:{version}",
        "openshell": f"{OPENSHELL_CONTAINER_REPOSITORY}:{version}",
    }


class VersionFile:
    """Represents a file containing version information."""

    def __init__(self, path: Path, pattern: str, description: str = ""):
        self.path = path
        self.pattern = pattern  # Regex pattern with {version} placeholder
        self.description = description

    def read_version(self) -> Optional[str]:
        """Read version from this file."""
        try:
            if not self.path.exists():
                return None

            content = self.path.read_text()
            # Convert pattern to regex
            regex_pattern = self.pattern.replace("{version}", r"([^\"']+)")
            match = re.search(regex_pattern, content, re.MULTILINE)
            return match.group(1) if match else None
        except Exception as e:
            print(f"Error reading {self.path}: {e}", file=sys.stderr)
            return None

    def write_version(self, new_version: str) -> bool:
        """Write new version to this file."""
        try:
            if not self.path.exists():
                print(f"Warning: {self.path} does not exist", file=sys.stderr)
                return False

            content = self.path.read_text()
            # Convert pattern to regex
            regex_pattern = self.pattern.replace("{version}", r"[^\"']+")
            new_content = self.pattern.replace("{version}", new_version)

            updated = re.sub(
                regex_pattern, new_content, content, count=1, flags=re.MULTILINE
            )

            self.path.write_text(updated)
            return True
        except Exception as e:
            print(f"Error writing {self.path}: {e}", file=sys.stderr)
            return False


class ReleaseHelper:
    """Project-agnostic release helper with auto-detection."""

    # Common version file patterns
    VERSION_PATTERNS = [
        # Python patterns
        {
            "glob": "**/pyproject.toml",
            "pattern": 'version = "{version}"',
            "description": "Python project metadata (pyproject.toml)",
        },
        {
            "glob": "**/setup.py",
            "pattern": 'version="{version}"',
            "description": "Python setup.py",
        },
        {
            "glob": "**/__init__.py",
            "pattern": '__version__ = "{version}"',
            "description": "Python package __init__.py",
        },
        {
            "glob": "**/__version__.py",
            "pattern": '__version__ = "{version}"',
            "description": "Python __version__.py",
        },
        # Node.js patterns
        {
            "glob": "**/package.json",
            "pattern": '"version": "{version}"',
            "description": "Node.js package.json",
        },
        # Generic patterns
        {"glob": "**/VERSION", "pattern": "{version}", "description": "VERSION file"},
    ]

    def __init__(self, repo_path: str = ".", config_file: str = ".release-config.json"):
        """
        Initialize ReleaseHelper with auto-detection.

        Args:
            repo_path: Path to repository root
            config_file: Name of config file (default: .release-config.json)
        """
        self.repo_path = Path(repo_path).resolve()
        self.config_path = self.repo_path / config_file
        self.changelog_path = self.repo_path / "CHANGELOG.md"

        # Load or detect configuration
        self.config = self._load_or_detect_config()
        self.version_files = self._create_version_files()

    def _load_or_detect_config(self) -> Dict[str, Any]:
        """Load config from file or auto-detect."""
        # Try to load existing config
        if self.config_path.exists():
            try:
                with open(self.config_path, "r") as f:
                    config = json.load(f)
                print(
                    f"✓ Loaded configuration from {self.config_path.name}",
                    file=sys.stderr,
                )
                return config
            except Exception as e:
                print(
                    f"Warning: Could not load {self.config_path}: {e}", file=sys.stderr
                )

        # Auto-detect
        print("🔍 Auto-detecting version files...", file=sys.stderr)
        detected = self._auto_detect_version_files()

        if not detected:
            print(
                "⚠️  No version files auto-detected. Please create .release-config.json",
                file=sys.stderr,
            )
            return {"version_files": [], "changelog": "CHANGELOG.md"}

        config = {
            "version_files": detected,
            "changelog": "CHANGELOG.md",
            "_comment": "Auto-generated by release helper. Edit as needed.",
        }

        # Save detected config
        self._save_config(config)

        return config

    def _auto_detect_version_files(self) -> List[Dict[str, str]]:
        """Auto-detect version files in the project."""
        detected = []

        for pattern_def in self.VERSION_PATTERNS:
            # Search for files matching this pattern
            matches = list(self.repo_path.glob(pattern_def["glob"]))

            for file_path in matches:
                # Make path relative to repo root
                try:
                    rel_path = file_path.relative_to(self.repo_path)
                except ValueError:
                    continue

                # Skip if in excluded directories
                if any(part.startswith(".") for part in rel_path.parts[:-1]):
                    continue  # Skip hidden directories
                if any(
                    part in ["node_modules", "venv", "__pycache__", "dist", "build"]
                    for part in rel_path.parts
                ):
                    continue  # Skip common excluded dirs

                # Check if this file actually contains a version
                test_file = VersionFile(file_path, pattern_def["pattern"])
                version = test_file.read_version()

                if version:
                    detected.append(
                        {
                            "path": str(rel_path),
                            "pattern": pattern_def["pattern"],
                            "description": pattern_def["description"],
                            "detected_version": version,
                        }
                    )
                    print(
                        f"  ✓ Found: {rel_path} (version: {version})", file=sys.stderr
                    )

        return detected

    def _save_config(self, config: Dict[str, Any]) -> bool:
        """Save configuration to .release-config.json."""
        try:
            with open(self.config_path, "w") as f:
                json.dump(config, f, indent=2)
            print(f"✓ Saved configuration to {self.config_path.name}", file=sys.stderr)
            return True
        except Exception as e:
            print(f"Warning: Could not save config: {e}", file=sys.stderr)
            return False

    def _create_version_files(self) -> List[VersionFile]:
        """Create VersionFile objects from config."""
        version_files = []

        for vf_config in self.config.get("version_files", []):
            path = self.repo_path / vf_config["path"]
            pattern = vf_config["pattern"]
            description = vf_config.get("description", "")

            version_files.append(VersionFile(path, pattern, description))

        return version_files

    def get_current_version(self) -> Tuple[Optional[str], bool]:
        """
        Get current version from all configured files.

        Returns:
            Tuple of (version, all_match)
            - version: The version string if all match, or None
            - all_match: True if all files have the same version
        """
        if not self.version_files:
            print("Error: No version files configured", file=sys.stderr)
            return None, False

        versions = {}
        for vf in self.version_files:
            ver = vf.read_version()
            if ver:
                versions[str(vf.path.relative_to(self.repo_path))] = ver

        if not versions:
            return None, False

        unique_versions = set(versions.values())
        all_match = len(unique_versions) == 1
        current_version = list(unique_versions)[0] if all_match else None

        if not all_match:
            print("⚠️  Version mismatch detected:", file=sys.stderr)
            for file, ver in versions.items():
                print(f"  {file}: {ver}", file=sys.stderr)

        return current_version, all_match

    def update_version(self, new_version: str) -> bool:
        """
        Update version in all configured files.

        Args:
            new_version: The new version string (e.g., "1.2.0")

        Returns:
            True if successful, False otherwise
        """
        if not self.version_files:
            print("Error: No version files configured", file=sys.stderr)
            return False

        try:
            # Update all files
            for vf in self.version_files:
                if not vf.write_version(new_version):
                    return False

            # Verify update
            version, all_match = self.get_current_version()
            if version == new_version and all_match:
                print(
                    f"✓ Version updated to {new_version} in all files", file=sys.stderr
                )
                return True
            else:
                print("Error: Version update verification failed", file=sys.stderr)
                return False

        except Exception as e:
            print(f"Error updating version: {e}", file=sys.stderr)
            return False

    def calculate_next_version(
        self, current_version: str, release_type: str
    ) -> Optional[str]:
        """
        Calculate next version based on release type.

        Args:
            current_version: Current version (e.g., "1.1.0-dev")
            release_type: One of "major", "minor", "patch", "test"

        Returns:
            Next version string or None if invalid
        """
        # Remove -dev or -test* suffix
        base_version = re.sub(r"-dev|-test\d*", "", current_version)

        # Parse semantic version
        match = re.match(r"^(\d+)\.(\d+)\.(\d+)$", base_version)
        if not match:
            print(f"Error: Invalid version format: {base_version}", file=sys.stderr)
            return None

        major, minor, patch = map(int, match.groups())

        if release_type == "major":
            return f"{major + 1}.0.0"
        elif release_type == "minor":
            return f"{major}.{minor + 1}.0"
        elif release_type == "patch":
            return f"{major}.{minor}.{patch + 1}"
        elif release_type == "test":
            return f"{major}.{minor}.{patch}-test1"
        else:
            print(f"Error: Invalid release type: {release_type}", file=sys.stderr)
            return None

    def update_changelog(self, version: str, date: Optional[str] = None) -> bool:
        """
        Update CHANGELOG.md by moving Unreleased section to new version.

        Args:
            version: New version (e.g., "1.2.0")
            date: Release date in YYYY-MM-DD format (defaults to today)

        Returns:
            True if successful, False otherwise
        """
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        changelog_file = self.repo_path / self.config.get("changelog", "CHANGELOG.md")

        if not changelog_file.exists():
            print(f"Warning: {changelog_file.name} not found", file=sys.stderr)
            return False

        try:
            content = changelog_file.read_text()

            # Check if Unreleased section exists
            if "## [Unreleased]" not in content:
                print(
                    "Warning: No [Unreleased] section found in CHANGELOG",
                    file=sys.stderr,
                )
                return False

            # Find the Unreleased section content
            unreleased_pattern = r"## \[Unreleased\]\s*(.*?)(?=## \[|$)"
            unreleased_match = re.search(unreleased_pattern, content, re.DOTALL)

            if not unreleased_match:
                print("Warning: Could not parse Unreleased section", file=sys.stderr)
                return False

            unreleased_content = unreleased_match.group(1).strip()

            # Check if there's actual content
            if not unreleased_content or unreleased_content.isspace():
                print("Warning: Unreleased section is empty", file=sys.stderr)
                return False

            # Create new version section
            version_section = f"## [{version}] - {date}\n\n{unreleased_content}\n\n"

            # Replace Unreleased section with new empty one + version section
            new_content = re.sub(
                r"## \[Unreleased\]\s*.*?(?=## \[|$)",
                f"## [Unreleased]\n\n{version_section}",
                content,
                count=1,
                flags=re.DOTALL,
            )

            # Update version links at the bottom (if they exist)
            repo_url_match = re.search(
                r"\[Unreleased\]: (https://github\.com/[^/]+/[^/]+)/compare/v([^.]+\.[^.]+\.[^.]+)\.\.\.HEAD",
                new_content,
            )

            if repo_url_match:
                repo_url = repo_url_match.group(1)

                # Update Unreleased link to compare from new version
                new_content = re.sub(
                    r"\[Unreleased\]: .*?\n",
                    f"[Unreleased]: {repo_url}/compare/v{version}...HEAD\n",
                    new_content,
                    count=1,
                )

                # Add new version link
                new_version_link = f"[{version}]: {repo_url}/releases/tag/v{version}\n"
                new_content = re.sub(
                    r"(\[Unreleased\]: .*?\n)",
                    f"\\1{new_version_link}",
                    new_content,
                    count=1,
                )

            changelog_file.write_text(new_content)
            print(f"✓ Updated CHANGELOG.md for version {version}", file=sys.stderr)
            return True

        except Exception as e:
            print(f"Error updating CHANGELOG: {e}", file=sys.stderr)
            return False

    def validate_prerequisites(
        self, release_type: str = "regular"
    ) -> Tuple[bool, List[str]]:
        """
        Validate prerequisites for a release.

        Args:
            release_type: "regular", "hotfix", or "test"

        Returns:
            Tuple of (all_valid, list_of_errors)
        """
        errors = []

        # Check version files exist
        if not self.version_files:
            errors.append("No version files configured")
        else:
            for vf in self.version_files:
                if not vf.path.exists():
                    errors.append(f"{vf.path.relative_to(self.repo_path)} not found")

        # Check CHANGELOG exists
        changelog_file = self.repo_path / self.config.get("changelog", "CHANGELOG.md")
        if not changelog_file.exists():
            errors.append(f"{changelog_file.name} not found")

        if errors:
            return False, errors

        # Check versions match
        version, all_match = self.get_current_version()
        if not all_match:
            errors.append("Version mismatch between files")

        # For regular releases, check CHANGELOG has content
        if release_type == "regular":
            try:
                content = changelog_file.read_text()
                if "## [Unreleased]" not in content:
                    errors.append("CHANGELOG missing [Unreleased] section")
                else:
                    # Check if Unreleased has content
                    unreleased_pattern = r"## \[Unreleased\]\s*(.*?)(?=## \[|$)"
                    match = re.search(unreleased_pattern, content, re.DOTALL)
                    if match:
                        unreleased_content = match.group(1).strip()
                        if not unreleased_content or unreleased_content.isspace():
                            errors.append("CHANGELOG [Unreleased] section is empty")
            except Exception as e:
                errors.append(f"Error reading CHANGELOG: {e}")

        return len(errors) == 0, errors

    def show_config(self):
        """Display current configuration."""
        print("\n📋 Current Configuration", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print(f"Config file: {self.config_path.name}", file=sys.stderr)
        print(f"Repository: {self.repo_path}", file=sys.stderr)
        print(f"\nVersion files ({len(self.version_files)}):", file=sys.stderr)

        for vf in self.version_files:
            rel_path = vf.path.relative_to(self.repo_path)
            version = vf.read_version()
            print(f"  • {rel_path}", file=sys.stderr)
            print(f"    Pattern: {vf.pattern}", file=sys.stderr)
            print(f"    Current: {version}", file=sys.stderr)
            if vf.description:
                print(f"    ({vf.description})", file=sys.stderr)

        print(
            f"\nChangelog: {self.config.get('changelog', 'CHANGELOG.md')}",
            file=sys.stderr,
        )
        print("=" * 60, file=sys.stderr)


class CursorHookVerifier:
    """Verifies Cursor IDE hook compatibility for release gating.

    Semi-automated 3-step flow:
    1. setup()   — create debug hook script, modify hooks.json
    2. (manual)  — user tests in Cursor
    3. analyze() — read debug logs, report PASS/FAIL per event
    cleanup() always runs after.
    """

    DEBUG_SCRIPT_NAME = "cursor-hook-debug.sh"
    DEBUG_LOG_PREFIX = "cursor-hook-debug-"
    SETTINGS_BACKUP_SUFFIX = ".cursor-verify-backup"
    DEBUG_HOOK_MARKER = "cursor-hook-debug.sh"

    try:
        from ai_guardian.constants import CURSOR_HOOK_EVENTS

        EXPECTED_EVENTS = list(CURSOR_HOOK_EVENTS)
    except ImportError:
        EXPECTED_EVENTS = [
            "beforeSubmitPrompt",
            "beforeReadFile",
            "beforeShellExecution",
            "afterShellExecution",
            "preToolUse",
            "postToolUse",
        ]

    def __init__(self, settings_path: Optional[str] = None, debug_dir: str = "/tmp"):
        self.debug_dir = Path(debug_dir)
        self.debug_script = self.debug_dir / self.DEBUG_SCRIPT_NAME
        if settings_path:
            self.settings_path = Path(settings_path)
        else:
            self.settings_path = Path("~/.cursor/hooks.json").expanduser()
        self.backup_path = self.settings_path.parent / (
            self.settings_path.name + self.SETTINGS_BACKUP_SUFFIX
        )

    def _clean_old_logs(self) -> int:
        """Remove old debug log files. Returns count removed."""
        count = 0
        for f in self.debug_dir.glob(f"{self.DEBUG_LOG_PREFIX}*.json"):
            f.unlink()
            count += 1
        return count

    def _write_debug_script(self) -> None:
        """Write the debug hook script that captures event data."""
        script_content = f"""#!/bin/bash
# Cursor hook debug probe — written by /release skill
# Captures hook event data for verification. Remove after analysis.
INPUT=$(cat)
EVENT=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('hook_event_name',d.get('hook_name',d.get('event','unknown'))))" 2>/dev/null || echo "unknown")
TS=$(date +%s%N)
echo "$INPUT" | python3 -c "
import sys, json, time
d = json.load(sys.stdin)
d['_debug_timestamp'] = time.time()
d['_debug_event'] = '${{EVENT}}'
json.dump(d, open('{self.debug_dir}/{self.DEBUG_LOG_PREFIX}' + '${{EVENT}}-${{TS}}.json', 'w'), indent=2)
" 2>/dev/null
echo '{{}}'
"""
        self.debug_script.write_text(script_content)
        self.debug_script.chmod(0o755)

    def _add_debug_hooks(self) -> bool:
        """Add debug hook entries to hooks.json for all event types."""
        if not self.settings_path.exists():
            print(
                f"Error: {self.settings_path} not found. Run ai-guardian setup --ide cursor first.",
                file=sys.stderr,
            )
            return False

        settings = json.loads(self.settings_path.read_text())

        debug_entry = {"command": str(self.debug_script)}

        hooks_obj = settings.setdefault("hooks", {})
        for event in self.EXPECTED_EVENTS:
            event_hooks = hooks_obj.setdefault(event, [])
            event_hooks.append(json.loads(json.dumps(debug_entry)))

        self.settings_path.write_text(json.dumps(settings, indent=2) + "\n")
        return True

    def setup(self) -> bool:
        """Step 1: Prepare debug hooks for Cursor verification."""
        print("Cursor Hook Compatibility Verification — Setup", file=sys.stderr)
        print("=" * 55, file=sys.stderr)

        cleaned = self._clean_old_logs()
        if cleaned:
            print(f"  Cleaned {cleaned} old debug log file(s)", file=sys.stderr)

        if self.backup_path.exists():
            print(
                f"  Warning: backup already exists at {self.backup_path}",
                file=sys.stderr,
            )
            print("  A previous verification may not have cleaned up.", file=sys.stderr)
            print("  Run cursor-verify-cleanup first.", file=sys.stderr)
            return False

        self._write_debug_script()
        print(f"  Created debug script: {self.debug_script}", file=sys.stderr)

        import shutil

        shutil.copy2(self.settings_path, self.backup_path)
        print(f"  Backed up settings to: {self.backup_path}", file=sys.stderr)

        if not self._add_debug_hooks():
            return False
        print(f"  Added debug hooks to: {self.settings_path}", file=sys.stderr)

        print("", file=sys.stderr)
        print("Setup complete. Now perform the manual Cursor test:", file=sys.stderr)
        print("", file=sys.stderr)
        print("  1. Upgrade Cursor to the latest version", file=sys.stderr)
        print("  2. Restart Cursor completely (quit and relaunch)", file=sys.stderr)
        print("  3. Open any project in Cursor", file=sys.stderr)
        print("  4. Type a prompt that triggers a file read", file=sys.stderr)
        print('     (e.g., "Read the contents of README.md")', file=sys.stderr)
        print("  5. Type a prompt that triggers a shell command", file=sys.stderr)
        print('     (e.g., "Run ls in the terminal")', file=sys.stderr)
        print("  6. Type a prompt that triggers a tool use", file=sys.stderr)
        print('     (e.g., "Add a comment to README.md")', file=sys.stderr)
        print("  7. Wait for the response to complete", file=sys.stderr)
        print("  8. Close the Cursor chat session", file=sys.stderr)
        print("  9. Return here and run: cursor-verify-analyze", file=sys.stderr)
        print("", file=sys.stderr)
        return True

    def analyze(self) -> Tuple[bool, Optional[str]]:
        """Step 3: Analyze debug logs and report per-event PASS/FAIL.

        Returns:
            (all_passed, cursor_version) tuple
        """
        print("Cursor Hook Compatibility Report", file=sys.stderr)
        print("=" * 40, file=sys.stderr)

        log_files = sorted(self.debug_dir.glob(f"{self.DEBUG_LOG_PREFIX}*.json"))

        if not log_files:
            print("", file=sys.stderr)
            print("No debug log files found.", file=sys.stderr)
            print("Did you perform the manual Cursor test?", file=sys.stderr)
            print(
                f"Expected files in: {self.debug_dir}/{self.DEBUG_LOG_PREFIX}*.json",
                file=sys.stderr,
            )
            return False, None

        events_found: Dict[str, int] = {}
        cursor_version = None

        for log_file in log_files:
            try:
                data = json.loads(log_file.read_text())
                raw_event = data.get(
                    "hook_event_name",
                    data.get(
                        "hook_name",
                        data.get("event", data.get("_debug_event", "unknown")),
                    ),
                )
                events_found[raw_event] = events_found.get(raw_event, 0) + 1

                cv = data.get("cursor_version")
                if cv and not cursor_version:
                    cursor_version = cv
            except (json.JSONDecodeError, OSError):
                continue

        if cursor_version:
            print(f"Cursor Version: {cursor_version}", file=sys.stderr)
        else:
            print(
                "Cursor Version: unknown (cursor_version field not found)",
                file=sys.stderr,
            )
        print("", file=sys.stderr)

        all_passed = True
        for event in self.EXPECTED_EVENTS:
            count = events_found.get(event, 0)
            status = "PASS" if count > 0 else "FAIL"
            if count == 0:
                all_passed = False
            fires = f"{count} fire(s) detected"
            print(f"  {event:<25} {status}  ({fires})", file=sys.stderr)

        print("", file=sys.stderr)
        if all_passed:
            print(
                f"Result: PASS — all {len(self.EXPECTED_EVENTS)} events verified",
                file=sys.stderr,
            )
        else:
            missing = [e for e in self.EXPECTED_EVENTS if events_found.get(e, 0) == 0]
            print(
                f"Result: FAIL — {len(missing)} event(s) missing: {', '.join(missing)}",
                file=sys.stderr,
            )
            print("Warning: Cursor may have changed hook support.", file=sys.stderr)

        if cursor_version:
            print(
                f"\nCursor version {cursor_version} tested on "
                f"{datetime.now().strftime('%Y-%m-%d')}.",
                file=sys.stderr,
            )

        return all_passed, cursor_version

    def cleanup(self) -> bool:
        """Remove debug hooks from hooks.json and delete debug files."""
        print("Cursor Hook Verification — Cleanup", file=sys.stderr)
        print("=" * 40, file=sys.stderr)

        if self.settings_path.exists():
            try:
                settings = json.loads(self.settings_path.read_text())
                removed = 0

                hooks_obj = settings.get("hooks", {})
                for event in list(hooks_obj.keys()):
                    if not isinstance(hooks_obj[event], list):
                        continue
                    original_len = len(hooks_obj[event])
                    hooks_obj[event] = [
                        entry
                        for entry in hooks_obj[event]
                        if not (
                            isinstance(entry, dict)
                            and self.DEBUG_HOOK_MARKER in entry.get("command", "")
                        )
                    ]
                    removed += original_len - len(hooks_obj[event])

                self.settings_path.write_text(json.dumps(settings, indent=2) + "\n")
                print(
                    f"  Removed {removed} debug hook(s) from hooks.json",
                    file=sys.stderr,
                )
            except (json.JSONDecodeError, OSError) as e:
                print(f"  Warning: Could not clean settings.json: {e}", file=sys.stderr)
                if self.backup_path.exists():
                    import shutil

                    shutil.copy2(self.backup_path, self.settings_path)
                    print("  Restored from backup", file=sys.stderr)

        if self.backup_path.exists():
            self.backup_path.unlink()
            print(f"  Removed backup: {self.backup_path}", file=sys.stderr)

        if self.debug_script.exists():
            self.debug_script.unlink()
            print(f"  Removed debug script: {self.debug_script}", file=sys.stderr)

        cleaned = self._clean_old_logs()
        if cleaned:
            print(f"  Removed {cleaned} debug log file(s)", file=sys.stderr)

        print("  Cleanup complete", file=sys.stderr)
        return True


def main():
    """CLI interface for release helper."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Project-agnostic release helper with auto-detection",
        epilog="Auto-detects version files or uses .release-config.json",
    )
    parser.add_argument(
        "--repo", default=".", help="Repository path (default: current directory)"
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Show config
    subparsers.add_parser("show-config", help="Show current configuration")

    # Get version
    subparsers.add_parser("get-version", help="Get current version from all files")

    # Update version
    update_parser = subparsers.add_parser(
        "update-version", help="Update version in all files"
    )
    update_parser.add_argument("version", help="New version (e.g., 1.2.0)")

    # Calculate next version
    calc_parser = subparsers.add_parser("calc-version", help="Calculate next version")
    calc_parser.add_argument("current", help="Current version")
    calc_parser.add_argument(
        "type", choices=["major", "minor", "patch", "test"], help="Release type"
    )

    # Update changelog
    changelog_parser = subparsers.add_parser(
        "update-changelog", help="Update CHANGELOG.md"
    )
    changelog_parser.add_argument("version", help="Version to release")
    changelog_parser.add_argument(
        "--date", help="Release date (YYYY-MM-DD, default: today)"
    )

    # Container image references
    container_parser = subparsers.add_parser(
        "container-images",
        help="Print versioned normal and OpenShell container image references",
    )
    container_parser.add_argument("version", help="Release version (e.g., 1.2.0)")

    # Validate
    validate_parser = subparsers.add_parser("validate", help="Validate prerequisites")
    validate_parser.add_argument(
        "--type",
        default="regular",
        choices=["regular", "hotfix", "test"],
        help="Release type",
    )

    # Re-detect
    subparsers.add_parser("detect", help="Re-run auto-detection and update config")

    # Cursor hook verification
    subparsers.add_parser(
        "cursor-verify-setup", help="Set up Cursor hook verification probes"
    )
    subparsers.add_parser(
        "cursor-verify-analyze", help="Analyze Cursor hook debug logs"
    )
    subparsers.add_parser(
        "cursor-verify-cleanup", help="Clean up Cursor verification artifacts"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    helper = ReleaseHelper(args.repo)

    if args.command == "show-config":
        helper.show_config()
        sys.exit(0)

    elif args.command == "get-version":
        version, all_match = helper.get_current_version()
        if version:
            print(f"Current version: {version}")
            print(f"All files match: {all_match}")
            sys.exit(0 if all_match else 1)
        else:
            print("Could not determine version", file=sys.stderr)
            sys.exit(1)

    elif args.command == "update-version":
        success = helper.update_version(args.version)
        sys.exit(0 if success else 1)

    elif args.command == "calc-version":
        next_version = helper.calculate_next_version(args.current, args.type)
        if next_version:
            print(next_version)
            sys.exit(0)
        else:
            sys.exit(1)

    elif args.command == "update-changelog":
        success = helper.update_changelog(args.version, args.date)
        sys.exit(0 if success else 1)

    elif args.command == "container-images":
        try:
            for name, image in get_container_image_references(args.version).items():
                print(f"{name}: {image}")
        except ValueError as error:
            print(f"Error: {error}", file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

    elif args.command == "validate":
        valid, errors = helper.validate_prerequisites(args.type)
        if valid:
            print("✓ All prerequisites validated")
            sys.exit(0)
        else:
            print("✗ Validation failed:", file=sys.stderr)
            for error in errors:
                print(f"  - {error}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "detect":
        print("Re-running auto-detection...")
        detected = helper._auto_detect_version_files()
        if detected:
            config = {
                "version_files": detected,
                "changelog": "CHANGELOG.md",
                "_comment": "Auto-generated by release helper. Edit as needed.",
            }
            helper._save_config(config)
            print(f"✓ Detected {len(detected)} version files")
        else:
            print("⚠️  No version files detected", file=sys.stderr)
            sys.exit(1)

    elif args.command == "cursor-verify-setup":
        verifier = CursorHookVerifier()
        success = verifier.setup()
        sys.exit(0 if success else 1)

    elif args.command == "cursor-verify-analyze":
        verifier = CursorHookVerifier()
        passed, cursor_version = verifier.analyze()
        sys.exit(0 if passed else 1)

    elif args.command == "cursor-verify-cleanup":
        verifier = CursorHookVerifier()
        success = verifier.cleanup()
        sys.exit(0 if success else 1)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
