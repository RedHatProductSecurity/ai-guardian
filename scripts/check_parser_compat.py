#!/usr/bin/env python3
"""
Check pattern server parser compatibility.

Verifies that registered parsers in PARSER_REGISTRY can still parse
responses from their corresponding pattern servers, and that parsed
rules compile successfully via PatternCache.

Also detects format drift: new/removed fields in server responses
compared to expected schemas.

Exit codes:
    0: All checks pass
    1: Compatibility failure (parse error, empty results, compile failure)
    2: Format version change detected (schema drift)
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore

import requests

from ai_guardian.patterns.cache import PatternCache
from ai_guardian.patterns.server_parsers import PARSER_REGISTRY, get_parser

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
FIXTURE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "ai_guardian_native_patterns.toml"

FALLBACK_LEAKTK_URL = "https://raw.githubusercontent.com"
FALLBACK_LEAKTK_ENDPOINT = "/leaktk/patterns/main/target/patterns/gitleaks/8.27.0"

EXPECTED_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "gitleaks": {
        "top_level_keys": {"rules"},
        "rule_fields": {
            "id", "description", "regex", "keywords",
            "secretGroup", "entropy", "allowlist", "allowlists", "path", "tags",
        },
        "required_rule_fields": {"id", "regex"},
    },
    "ai-guardian": {
        "top_level_keys": {"rules"},
        "rule_fields": {
            "id", "match_type", "regex", "description",
            "redaction_strategy", "keywords",
        },
        "required_rule_fields": {"id", "match_type", "regex"},
    },
}


def get_leaktk_url() -> str:
    """Read the LeakTK pattern server URL from pyproject.toml."""
    pyproject_path = PROJECT_ROOT / "pyproject.toml"
    try:
        with open(pyproject_path, "rb") as f:
            config = tomllib.load(f)
        ps = config["tool"]["ai-guardian"]["scanners"]["pattern_servers"]["leaktk"]
        url = ps.get("url", FALLBACK_LEAKTK_URL)
        endpoint = ps.get("patterns_endpoint", FALLBACK_LEAKTK_ENDPOINT)
        return f"{url.rstrip('/')}{endpoint}"
    except (KeyError, FileNotFoundError, tomllib.TOMLDecodeError):
        return f"{FALLBACK_LEAKTK_URL}{FALLBACK_LEAKTK_ENDPOINT}"


def fetch_url(url: str, retries: int = 1) -> Optional[str]:
    """Fetch URL content with retry logic."""
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            if attempt < retries:
                print(f"  ⚠️  Retry {attempt + 1}/{retries} after error: {e}")
                time.sleep(5)
            else:
                print(f"  ❌ Failed to fetch {url}: {e}")
                return None
    return None


def fetch_pattern_data(format_name: str) -> Optional[Dict[str, Any]]:
    """Fetch raw TOML data for a given parser format.

    Returns parsed TOML dict, or None on failure.
    """
    if format_name == "gitleaks":
        url = get_leaktk_url()
        print(f"  Fetching gitleaks patterns from {url}")
        content = fetch_url(url)
        if content is None:
            return None
        try:
            return tomllib.loads(content)
        except tomllib.TOMLDecodeError as e:
            print(f"  ❌ Invalid TOML from server: {e}")
            return None

    elif format_name == "ai-guardian":
        fixture = FIXTURE_PATH
        print(f"  Loading ai-guardian fixture from {fixture}")
        if not fixture.exists():
            print(f"  ❌ Fixture not found: {fixture}")
            return None
        try:
            with open(fixture, "rb") as f:
                return tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            print(f"  ❌ Invalid TOML in fixture: {e}")
            return None

    else:
        print(f"  ⚠️  No data source configured for format: {format_name}")
        return None


def extract_schema(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract structural schema from a TOML response."""
    top_level_keys = set(raw_data.keys())
    rule_fields: Set[str] = set()

    rules = raw_data.get("rules", [])
    if isinstance(rules, list):
        for rule in rules:
            if isinstance(rule, dict):
                rule_fields.update(rule.keys())

    return {
        "top_level_keys": top_level_keys,
        "rule_fields": rule_fields,
    }


def compare_schemas(
    actual: Dict[str, Any],
    expected: Dict[str, Any],
) -> Dict[str, Any]:
    """Compare actual schema against expected, report differences."""
    actual_fields = actual.get("rule_fields", set())
    expected_fields = expected.get("rule_fields", set())
    required_fields = expected.get("required_rule_fields", set())

    new_fields = sorted(actual_fields - expected_fields)
    removed_fields = sorted(expected_fields - actual_fields)
    missing_required = sorted(required_fields - actual_fields)

    if missing_required:
        status = "changed"
    elif new_fields:
        status = "warning"
    else:
        status = "ok"

    return {
        "status": status,
        "new_fields": new_fields,
        "removed_fields": removed_fields,
        "missing_required": missing_required,
    }


def run_compat_check(output_file: str) -> int:
    """Run parser compatibility check for all registered formats."""
    print("=" * 60)
    print("Parser Compatibility Check")
    print("=" * 60)

    results = {}
    has_failure = False

    for format_name in sorted(PARSER_REGISTRY.keys()):
        print(f"\n📋 Checking format: {format_name}")

        raw_data = fetch_pattern_data(format_name)
        if raw_data is None:
            results[format_name] = {
                "status": "FAIL",
                "error": "Failed to fetch pattern data",
            }
            has_failure = True
            print(f"  ❌ FAIL: Could not fetch data for {format_name}")
            continue

        parser = get_parser(format_name)
        if parser is None:
            results[format_name] = {
                "status": "FAIL",
                "error": f"No parser registered for {format_name}",
            }
            has_failure = True
            print(f"  ❌ FAIL: No parser for {format_name}")
            continue

        parsed_rules = parser.parse(raw_data)
        if not parsed_rules:
            results[format_name] = {
                "status": "FAIL",
                "error": "Parser returned empty results",
                "raw_rule_count": len(raw_data.get("rules", [])),
            }
            has_failure = True
            print(f"  ❌ FAIL: Parser returned 0 rules")
            continue

        print(f"  ✅ Parsed {len(parsed_rules)} rules")

        cache = PatternCache()
        cache.load_rules(parsed_rules, category="compat_test")
        compiled_count = cache.rule_count

        if compiled_count == 0:
            results[format_name] = {
                "status": "FAIL",
                "error": "No rules compiled successfully",
                "parsed_count": len(parsed_rules),
            }
            has_failure = True
            print(f"  ❌ FAIL: 0 rules compiled (of {len(parsed_rules)} parsed)")
            continue

        results[format_name] = {
            "status": "OK",
            "parsed_count": len(parsed_rules),
            "compiled_count": compiled_count,
        }
        print(f"  ✅ Compiled {compiled_count}/{len(parsed_rules)} rules")

    print("\n" + "=" * 60)
    if has_failure:
        print("❌ Parser compatibility check FAILED")
    else:
        print("✅ All parser compatibility checks passed")
    print("=" * 60)

    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults written to {output_file}")

    return 1 if has_failure else 0


def run_format_version_check(output_file: str) -> int:
    """Check for format drift in pattern server responses."""
    print("=" * 60)
    print("Format Version Check")
    print("=" * 60)

    results = {}
    has_changes = False

    for format_name in sorted(PARSER_REGISTRY.keys()):
        print(f"\n📋 Checking schema for: {format_name}")

        expected = EXPECTED_SCHEMAS.get(format_name)
        if expected is None:
            print(f"  ⚠️  No expected schema defined for {format_name}, skipping")
            results[format_name] = {"status": "skipped", "reason": "no expected schema"}
            continue

        raw_data = fetch_pattern_data(format_name)
        if raw_data is None:
            results[format_name] = {
                "status": "error",
                "error": "Failed to fetch pattern data",
            }
            continue

        actual = extract_schema(raw_data)
        comparison = compare_schemas(actual, expected)

        results[format_name] = comparison
        results[format_name]["actual_rule_fields"] = sorted(actual.get("rule_fields", set()))
        results[format_name]["expected_rule_fields"] = sorted(expected.get("rule_fields", set()))

        if comparison["status"] == "ok":
            print(f"  ✅ Schema matches expected ({len(actual['rule_fields'])} fields)")
        elif comparison["status"] == "warning":
            has_changes = True
            print(f"  ⚠️  New fields detected: {', '.join(comparison['new_fields'])}")
        elif comparison["status"] == "changed":
            has_changes = True
            print(f"  ❌ Required fields missing: {', '.join(comparison['missing_required'])}")
            if comparison["new_fields"]:
                print(f"      New fields: {', '.join(comparison['new_fields'])}")

    print("\n" + "=" * 60)
    if has_changes:
        print("⚠️  Format changes detected — parser update may be needed")
    else:
        print("✅ All format schemas match expectations")
    print("=" * 60)

    with open(output_file, "w") as f:
        json.dump(results, f, indent=2, default=_json_default)
    print(f"\nResults written to {output_file}")

    return 2 if has_changes else 0


def _json_default(obj: Any) -> Any:
    if isinstance(obj, set):
        return sorted(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check pattern server parser compatibility"
    )
    parser.add_argument(
        "--compat-check",
        action="store_true",
        help="Run parser compatibility check (parse + compile)",
    )
    parser.add_argument(
        "--format-version-check",
        action="store_true",
        help="Run format version check (schema drift detection)",
    )
    parser.add_argument(
        "--output",
        default="parser-compat-results.json",
        help="Output JSON file path (default: parser-compat-results.json)",
    )
    args = parser.parse_args()

    if args.compat_check:
        sys.exit(run_compat_check(args.output))
    elif args.format_version_check:
        sys.exit(run_format_version_check(args.output))
    else:
        code1 = run_compat_check(args.output.replace(".json", "-compat.json"))
        code2 = run_format_version_check(args.output.replace(".json", "-format.json"))
        sys.exit(max(code1, code2))


if __name__ == "__main__":
    main()
