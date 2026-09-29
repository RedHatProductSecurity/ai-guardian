"""Regression tests for immutable violation metadata propagation."""

import re

from ai_guardian.scanners.config_scanner import ConfigFileScanner


def test_config_exfil_details_mark_any_immutable_finding():
    scanner = ConfigFileScanner({"enabled": True})
    scanner._compiled_patterns = [
        {
            "name": "configurable_rule",
            "regex": re.compile(r"first"),
            "description": "configurable test rule",
            "immutable": False,
        },
        {
            "name": "immutable_rule",
            "regex": re.compile(r"second"),
            "description": "immutable test rule",
            "immutable": True,
        },
    ]

    detected, _, details = scanner.check_command("first second")

    assert detected is True
    assert details["is_immutable"] is True
