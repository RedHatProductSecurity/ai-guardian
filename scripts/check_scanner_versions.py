#!/usr/bin/env python3
"""
Check if pinned scanner versions exist and are downloadable.

This script verifies that all pinned scanner versions in pyproject.toml
still exist on GitHub releases and are downloadable. It prevents CI failures
when versions are yanked or repositories are archived.

With --check-updates flag, also checks for version updates and calculates
age of pinned versions to alert when dependencies are outdated.

Exit codes:
    0: All pinned scanner versions exist and are downloadable (and up to date if checking updates)
    1: One or more pinned scanner versions do not exist or are outdated (>30 days)
"""

import sys
import json
import argparse
import requests
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

try:
    import tomllib
except ImportError:  # Python 3.9 and 3.10
    import tomli as tomllib


def get_latest_version(repo: str) -> Optional[str]:
    """Get latest version from GitHub releases."""
    api_url = f"https://api.github.com/repos/{repo}/releases/latest"

    try:
        response = requests.get(api_url, timeout=10)
        response.raise_for_status()
        data = response.json()
        tag = data.get('tag_name', '')
        # Remove 'v' prefix if present
        return tag.lstrip('v')
    except requests.RequestException:
        return None


def get_latest_leaktk_pattern_version() -> Optional[str]:
    """Get latest LeakTK pattern version from GitHub directory listing."""
    # LeakTK patterns are organized by gitleaks version in directories
    # https://github.com/leaktk/patterns/tree/main/target/patterns/gitleaks/
    api_url = "https://api.github.com/repos/leaktk/patterns/contents/target/patterns/gitleaks"

    try:
        response = requests.get(api_url, timeout=10)
        response.raise_for_status()
        contents = response.json()

        # Filter for directories (type == "dir") and extract version numbers
        versions = []
        for item in contents:
            if item.get('type') == 'dir':
                name = item.get('name', '')
                # Version directories are like "8.27.0", "8.30.0", etc.
                if name and name[0].isdigit():
                    versions.append(name)

        if not versions:
            return None

        # Sort versions semantically and return the latest
        versions.sort(key=lambda v: tuple(map(int, v.split('.'))))
        return versions[-1]

    except (requests.RequestException, ValueError):
        return None


def get_version_age(repo: str, version: str) -> Optional[int]:
    """Get age of version in days."""
    api_url = f"https://api.github.com/repos/{repo}/releases/tags/v{version}"

    try:
        response = requests.get(api_url, timeout=10)
        response.raise_for_status()
        data = response.json()

        published_at = data.get('published_at')
        if not published_at:
            return None

        release_date = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
        age = datetime.now(release_date.tzinfo) - release_date
        return age.days

    except (requests.RequestException, ValueError):
        return None


def compare_versions(v1: str, v2: str) -> int:
    """
    Compare semantic versions.

    Returns:
        -1 if v1 < v2
        0 if v1 == v2
        1 if v1 > v2
    """
    def parse_version(v):
        return tuple(map(int, v.split('.')))

    try:
        p1 = parse_version(v1)
        p2 = parse_version(v2)

        if p1 < p2:
            return -1
        elif p1 > p2:
            return 1
        else:
            return 0
    except (ValueError, AttributeError):
        return 0


def expected_asset_name(scanner_name: str, version: str, platform: str) -> str:
    """Return upstream asset names for Secretlint and GitGuardian releases."""
    system, arch = platform.split('_', 1)

    if scanner_name == 'secretlint':
        extension = '.exe' if system == 'windows' else ''
        return f'secretlint-{version}-{system}-{arch}{extension}'

    if scanner_name == 'gitguardian':
        if system == 'linux':
            gg_arch = {'x64': 'x86_64', 'arm64': 'aarch64'}.get(arch, arch)
            return f'ggshield-{version}-{gg_arch}-unknown-linux-gnu.tar.gz'
        if system == 'darwin':
            gg_arch = {'x64': 'x86_64', 'arm64': 'arm64'}.get(arch, arch)
            return f'ggshield-{version}-{gg_arch}-apple-darwin.tar.gz'
        if system == 'windows':
            windows_arch = {'x64': 'x86_64'}.get(arch, arch)
            return f'ggshield-{version}-{windows_arch}-pc-windows-msvc.zip'

    raise ValueError(f'No asset naming rule for {scanner_name} on {platform}')


def check_scanner_exists(repo: str, version: str, scanner_name: str, platform: str = "linux_x64") -> dict:
    """
    Check if a scanner version exists on GitHub releases.

    Args:
        repo: GitHub repo (e.g., "gitleaks/gitleaks")
        version: Version to check (e.g., "8.30.1")
        scanner_name: Name of scanner configured in pyproject.toml
        platform: Platform string (e.g., "linux_x64")

    Returns:
        dict with exists, download_url, error
    """
    # detect-secrets is a Python package (pip install detect-secrets), no binary releases
    if scanner_name == "detect-secrets":
        # Check if PyPI package exists at this version
        pypi_url = f"https://pypi.org/pypi/detect-secrets/{version}/json"
        try:
            response = requests.get(pypi_url, timeout=10)
            if response.status_code == 200:
                return {
                    'exists': True,
                    'download_url': f'https://pypi.org/project/detect-secrets/{version}/',
                    'size_mb': 'N/A (Python package)'
                }
            else:
                return {
                    'exists': False,
                    'error': f'PyPI package detect-secrets v{version} not found'
                }
        except requests.RequestException as e:
            return {
                'exists': False,
                'error': f'Error checking PyPI: {e}'
            }

    # Try release API first
    api_url = f"https://api.github.com/repos/{repo}/releases/tags/v{version}"

    try:
        response = requests.get(api_url, timeout=10)

        if response.status_code == 404:
            return {
                'exists': False,
                'error': f'Release v{version} not found in {repo}'
            }

        response.raise_for_status()
        release_data = response.json()

        # Build expected asset name based on scanner naming conventions
        # gitleaks/betterleaks: scanner_version_platform.tar.gz (e.g., gitleaks_8.30.1_linux_x64.tar.gz)
        # leaktk: scanner-version-system-arch.tar.xz with x86_64 instead of x64 (e.g., leaktk-0.2.10-linux-x86_64.tar.xz)
        # trufflehog: scanner_version_system_arch.tar.gz with amd64 instead of x64 (e.g., trufflehog_3.88.0_linux_amd64.tar.gz)
        if scanner_name in ('secretlint', 'gitguardian'):
            asset_name = expected_asset_name(scanner_name, version, platform)
        elif scanner_name == "leaktk":
            # leaktk uses hyphens, separate system and arch, and x86_64 instead of x64
            system, arch = platform.split('_', 1)
            leaktk_arch = "x86_64" if arch == "x64" else arch
            asset_name = f"{scanner_name}-{version}-{system}-{leaktk_arch}.tar.xz"
        elif scanner_name == "trufflehog":
            # trufflehog uses amd64 instead of x64
            system, arch = platform.split('_', 1)
            trufflehog_arch = "amd64" if arch == "x64" else arch
            asset_name = f"{scanner_name}_{version}_{system}_{trufflehog_arch}.tar.gz"
        else:
            # gitleaks and betterleaks use underscores
            asset_name = f"{scanner_name}_{version}_{platform}.tar.gz"

        assets = release_data.get('assets', [])
        matching_asset = next(
            (a for a in assets if a['name'] == asset_name),
            None
        )

        if not matching_asset:
            return {
                'exists': False,
                'error': f'Asset {asset_name} not found in release v{version}'
            }

        # Asset exists in release - no need for HEAD request since GitHub API is authoritative
        return {
            'exists': True,
            'download_url': matching_asset['browser_download_url'],
            'size_mb': round(matching_asset['size'] / 1024 / 1024, 2)
        }

    except requests.RequestException as e:
        return {
            'exists': False,
            'error': f'Network error checking {repo} v{version}: {e}'
        }


def check_versions(output_file: str = 'versions.json'):
    """Check all scanner versions and output results."""

    # Load pyproject.toml
    pyproject_path = Path('pyproject.toml')
    if not pyproject_path.exists():
        print("❌ pyproject.toml not found")
        sys.exit(1)

    with open(pyproject_path, 'rb') as f:
        config = tomllib.load(f)

    scanners_config = config.get('tool', {}).get('ai-guardian', {}).get('scanners', {})
    repos_config = scanners_config.get('repos', {})

    if not scanners_config:
        print("❌ No scanner versions found in pyproject.toml")
        sys.exit(1)

    print("Checking scanner version updates...\n")

    results = {}
    has_warnings = False

    # Check scanner versions
    for scanner, pinned_version in scanners_config.items():
        if scanner == 'repos':
            continue

        repo = repos_config.get(scanner)
        if not repo:
            continue

        print(f"Checking {scanner}...")

        latest_version = get_latest_version(repo)
        age_days = get_version_age(repo, pinned_version)

        is_outdated = False
        status = 'OK'

        if latest_version and compare_versions(pinned_version, latest_version) < 0:
            is_outdated = True
            status = 'OUTDATED'

        if age_days and age_days > 30:
            status = 'WARNING'
            has_warnings = True

        results[scanner] = {
            'pinned_version': pinned_version,
            'latest_version': latest_version or 'unknown',
            'is_outdated': is_outdated,
            'age_days': age_days,
            'status': status,
            'repo': repo
        }

        print(f"  Pinned: v{pinned_version}")
        print(f"  Latest: v{latest_version or 'unknown'}")
        print(f"  Age: {age_days or 'unknown'} days")
        print(f"  Status: {status}")
        print()

    # Check LeakTK pattern server version (from ai-guardian-example.json)
    print("Checking LeakTK pattern server version...")

    # Parse current version from ai-guardian-example.json
    example_config_path = Path('ai-guardian-example.json')
    current_leaktk_version = None

    if example_config_path.exists():
        try:
            with open(example_config_path, 'r') as f:
                import json as json_lib
                example_config = json_lib.load(f)
                # Navigate to secret_scanning.pattern_server._leaktk_example_config.patterns_endpoint
                pattern_endpoint = (example_config
                    .get('secret_scanning', {})
                    .get('pattern_server', {})
                    .get('_leaktk_example_config', {})
                    .get('patterns_endpoint', ''))

                # Extract version from "/leaktk/patterns/main/target/patterns/gitleaks/8.27.0"
                if pattern_endpoint:
                    parts = pattern_endpoint.split('/')
                    if len(parts) > 0:
                        current_leaktk_version = parts[-1]
        except (json_lib.JSONDecodeError, KeyError):
            pass

    latest_leaktk_version = get_latest_leaktk_pattern_version()

    leaktk_is_outdated = False
    leaktk_status = 'OK'

    if current_leaktk_version and latest_leaktk_version:
        if compare_versions(current_leaktk_version, latest_leaktk_version) < 0:
            leaktk_is_outdated = True
            leaktk_status = 'OUTDATED'
            has_warnings = True

    results['leaktk_patterns'] = {
        'pinned_version': current_leaktk_version or 'unknown',
        'latest_version': latest_leaktk_version or 'unknown',
        'is_outdated': leaktk_is_outdated,
        'age_days': None,  # Age not tracked for pattern directories
        'status': leaktk_status,
        'repo': 'leaktk/patterns',
        'update_locations': [
            'ai-guardian-example.json: secret_scanning.pattern_server._leaktk_example_config.patterns_endpoint',
            'pyproject.toml: [tool.ai-guardian.scanners.pattern_server] section (add if missing)'
        ]
    }

    print(f"  Current pattern version: {current_leaktk_version or 'unknown'}")
    print(f"  Latest pattern version: {latest_leaktk_version or 'unknown'}")
    print(f"  Status: {leaktk_status}")
    print()

    # Write results to JSON for workflow
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"Results written to {output_file}")

    # Exit with appropriate code
    if has_warnings:
        print("\n⚠️  Some scanner versions or patterns are outdated")
        sys.exit(1)
    else:
        print("\n✅ All scanner versions and patterns are up to date")
        sys.exit(0)


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Check scanner versions')
    parser.add_argument('--output', default='versions.json', help='Output file for version check results')
    parser.add_argument('--check-updates', action='store_true', help='Check for version updates and calculate age')

    args = parser.parse_args()

    if args.check_updates:
        # Check for updates and report outdated versions
        check_versions(args.output)
    else:
        # Original behavior: just verify existence
        check_existence()


def check_existence():
    """Original function to check if versions exist (no update checking)."""
    # Load pyproject.toml
    pyproject_path = Path('pyproject.toml')
    if not pyproject_path.exists():
        print("❌ pyproject.toml not found")
        sys.exit(1)

    with open(pyproject_path, 'rb') as f:
        config = tomllib.load(f)

    scanners_config = config.get('tool', {}).get('ai-guardian', {}).get('scanners', {})
    repos_config = scanners_config.get('repos', {})

    if not scanners_config:
        print("❌ No scanner versions found in pyproject.toml")
        sys.exit(1)

    print("Checking pinned scanner versions...\n")

    all_exist = True

    for scanner, version in scanners_config.items():
        if scanner == 'repos':
            continue  # Skip repos section

        repo = repos_config.get(scanner)
        if not repo:
            print(f"⚠️  {scanner}: No repository configured, skipping")
            continue

        print(f"Checking {scanner} v{version} ({repo})...")

        result = check_scanner_exists(repo, version, scanner)

        if result['exists']:
            print(f"  ✅ EXISTS - {result['download_url']}")
            print(f"     Size: {result['size_mb']} MB")
        else:
            print(f"  ❌ NOT FOUND - {result['error']}")
            all_exist = False

        print()

    if not all_exist:
        print("\n🚨 CRITICAL: One or more pinned scanner versions do not exist!")
        print("Action required: Update pyproject.toml with valid versions")
        sys.exit(1)

    print("✅ All pinned scanner versions exist and are downloadable")
    sys.exit(0)


if __name__ == '__main__':
    main()
