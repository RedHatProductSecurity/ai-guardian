#!/usr/bin/env python3
"""
SARIF (Static Analysis Results Interchange Format) output formatter.

Implements SARIF 2.1.0 specification for CI/CD integration with
GitHub Code Scanning, GitLab Security Dashboards, and other tools.

Spec: https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html
"""

import json
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone


class SARIFFormatter:
    """Format security findings as SARIF 2.1.0 JSON output."""

    # SARIF rule definitions for AI Guardian security checks
    RULES = {
        "SSRF-001": {
            "id": "SSRF-001",
            "name": "SSRFDetection",
            "shortDescription": {
                "text": "Server-Side Request Forgery attempt detected"
            },
            "fullDescription": {
                "text": "Detects attempts to access internal/private IP addresses, cloud metadata endpoints, "
                "or perform URL redirects that could lead to SSRF attacks."
            },
            "helpUri": "https://github.com/RedHatProductSecurity/ai-guardian#ssrf-protection",
            "defaultConfiguration": {"level": "error"},
            "properties": {
                "tags": ["security", "ssrf", "network"],
                "precision": "high",
            },
        },
        "UNICODE-001": {
            "id": "UNICODE-001",
            "name": "UnicodeAttackDetection",
            "shortDescription": {"text": "Unicode attack detected"},
            "fullDescription": {
                "text": "Detects malicious Unicode characters including zero-width characters, "
                "bidirectional override characters, homoglyphs, and tag characters used for "
                "prompt injection or obfuscation."
            },
            "helpUri": "https://github.com/RedHatProductSecurity/ai-guardian#unicode-attack-detection",
            "defaultConfiguration": {"level": "error"},
            "properties": {
                "tags": ["security", "unicode", "prompt-injection"],
                "precision": "high",
            },
        },
        "CONFIG-001": {
            "id": "CONFIG-001",
            "name": "ConfigFileExfiltration",
            "shortDescription": {
                "text": "Credential exfiltration pattern in config file"
            },
            "fullDescription": {
                "text": "Detects patterns in AI configuration files (CLAUDE.md, AGENTS.md, etc.) "
                "that could exfiltrate credentials or sensitive data through curl, wget, "
                "base64 encoding, or cloud storage uploads."
            },
            "helpUri": "https://github.com/RedHatProductSecurity/ai-guardian#config-file-scanner",
            "defaultConfiguration": {"level": "error"},
            "properties": {
                "tags": ["security", "exfiltration", "credentials"],
                "precision": "high",
            },
        },
        "SECRET-001": {
            "id": "SECRET-001",
            "name": "SecretDetected",
            "shortDescription": {"text": "Secret or credential detected"},
            "fullDescription": {
                "text": "Detects secrets, API keys, tokens, passwords, and other credentials "
                "using pattern matching from Gitleaks and custom patterns."
            },
            "helpUri": "https://github.com/RedHatProductSecurity/ai-guardian#secret-scanning",
            "defaultConfiguration": {"level": "error"},
            "properties": {
                "tags": ["security", "secrets", "credentials"],
                "precision": "high",
            },
        },
        "PII-001": {
            "id": "PII-001",
            "name": "PIIDetected",
            "shortDescription": {
                "text": "Personally identifiable information detected"
            },
            "fullDescription": {
                "text": "Detects personally identifiable information (PII) including social security numbers, "
                "credit card numbers, phone numbers, email addresses, passport numbers, and IBANs."
            },
            "helpUri": "https://github.com/RedHatProductSecurity/ai-guardian#pii-detection",
            "defaultConfiguration": {"level": "warning"},
            "properties": {"tags": ["security", "pii", "privacy"], "precision": "high"},
        },
        "PROMPT-INJECTION-001": {
            "id": "PROMPT-INJECTION-001",
            "name": "PromptInjection",
            "shortDescription": {"text": "Prompt injection pattern detected"},
            "fullDescription": {
                "text": "Detects prompt injection attempts including instruction overrides, "
                "role manipulation, and other techniques to manipulate AI behavior."
            },
            "helpUri": "https://github.com/RedHatProductSecurity/ai-guardian#prompt-injection-detection",
            "defaultConfiguration": {"level": "warning"},
            "properties": {
                "tags": ["security", "prompt-injection", "ai"],
                "precision": "medium",
            },
        },
        "SUPPLY-CHAIN-001": {
            "id": "SUPPLY-CHAIN-001",
            "name": "SupplyChainThreat",
            "shortDescription": {"text": "Supply chain threat in agent config"},
            "fullDescription": {
                "text": "Detects malicious patterns in agent configuration files including "
                "download-and-execute chains, obfuscation, environment variable hijacking, "
                "and reverse shells."
            },
            "helpUri": "https://github.com/RedHatProductSecurity/ai-guardian#supply-chain-scanning",
            "defaultConfiguration": {"level": "error"},
            "properties": {
                "tags": ["security", "supply-chain", "agent-config"],
                "precision": "high",
            },
        },
    }

    def __init__(self, version: str = "1.5.0"):
        """
        Initialize SARIF formatter.

        Args:
            version: AI Guardian version string
        """
        self.version = version

    def create_sarif_report(
        self,
        results: List[Dict[str, Any]],
        scan_path: str = ".",
        invocation_time: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a complete SARIF 2.1.0 report.

        Args:
            results: List of security findings, each with:
                - rule_id: Rule ID (e.g., "SSRF-001")
                - level: Severity level ("error", "warning", "note")
                - message: Description of the finding
                - file_path: Path to the file (optional)
                - line_number: Line number (optional)
                - snippet: Code snippet (optional)
                - details: Additional context (optional)
            scan_path: Base path that was scanned
            invocation_time: ISO 8601 timestamp (defaults to now)

        Returns:
            SARIF 2.1.0 compliant dictionary
        """
        if invocation_time is None:
            invocation_time = (
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            )

        sarif_results = []
        for result in results:
            sarif_result = self._create_sarif_result(result)
            if sarif_result:
                sarif_results.append(sarif_result)

        # Collect unique rules used in this report
        used_rules = set(r.get("rule_id") for r in results if r.get("rule_id"))
        rules = [self.RULES[rule_id] for rule_id in used_rules if rule_id in self.RULES]

        return {
            "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "AI Guardian",
                            "version": self.version,
                            "informationUri": "https://github.com/RedHatProductSecurity/ai-guardian",
                            "semanticVersion": self.version,
                            "rules": rules,
                        }
                    },
                    "results": sarif_results,
                    "invocations": [
                        {
                            "executionSuccessful": True,
                            "endTimeUtc": invocation_time,
                            "workingDirectory": {"uri": self._file_uri(scan_path)},
                        }
                    ],
                }
            ],
        }

    def _create_sarif_result(self, finding: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Convert a single finding to SARIF result format.

        Args:
            finding: Security finding dictionary

        Returns:
            SARIF result object or None if invalid
        """
        rule_id = finding.get("rule_id")
        if not rule_id:
            return None

        result = {
            "ruleId": rule_id,
            "level": self._map_level(finding.get("level", "warning")),
            "message": {"text": finding.get("message", "Security issue detected")},
        }

        # Add location information if available
        file_path = finding.get("file_path")
        if file_path:
            location = {
                "physicalLocation": {
                    "artifactLocation": {"uri": file_path, "uriBaseId": "%SRCROOT%"}
                }
            }

            # Add region (line number, column, snippet) if available
            line_number = finding.get("line_number")
            snippet = finding.get("snippet")
            start_col = finding.get("start_column")
            end_col = finding.get("end_column")
            if line_number is not None or snippet is not None or start_col is not None:
                region = {}
                if line_number is not None:
                    region["startLine"] = int(line_number)
                if start_col is not None:
                    region["startColumn"] = int(start_col) + 1
                if end_col is not None:
                    region["endColumn"] = int(end_col) + 1
                if snippet is not None:
                    region["snippet"] = {"text": snippet}
                location["physicalLocation"]["region"] = region

            result["locations"] = [location]

        # Add additional details as properties
        if finding.get("details"):
            result["properties"] = {"details": finding["details"]}

        return result

    def _map_level(self, level: str) -> str:
        """
        Map custom severity levels to SARIF levels.

        SARIF supports: "error", "warning", "note", "none"

        Args:
            level: Custom severity level

        Returns:
            SARIF level string
        """
        level_map = {
            "error": "error",
            "high": "error",
            "critical": "error",
            "warning": "warning",
            "medium": "warning",
            "low": "note",
            "info": "note",
            "note": "note",
        }
        return level_map.get(level.lower(), "warning")

    def _file_uri(self, path: str) -> str:
        """
        Convert file path to URI format.

        Args:
            path: File system path

        Returns:
            URI string
        """
        # Simple conversion - could be enhanced for Windows paths
        if not path.startswith("/"):
            return f"file:///{path}"
        return f"file://{path}"

    def write_sarif_file(
        self,
        results: List[Dict[str, Any]],
        output_path: str,
        scan_path: str = ".",
        invocation_time: Optional[str] = None,
    ) -> None:
        """
        Create and write SARIF report to file.

        Args:
            results: List of security findings
            output_path: Path to write SARIF JSON file
            scan_path: Base path that was scanned
            invocation_time: ISO 8601 timestamp (defaults to now)
        """
        sarif_report = self.create_sarif_report(results, scan_path, invocation_time)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(sarif_report, f, indent=2)


def create_ssrf_finding(
    url: str,
    reason: str,
    file_path: Optional[str] = None,
    line_number: Optional[int] = None,
    snippet: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a SARIF finding for SSRF detection.

    Args:
        url: The problematic URL
        reason: Why this URL was flagged
        file_path: File where URL was found
        line_number: Line number in file
        snippet: Code snippet

    Returns:
        Finding dictionary for SARIF formatter
    """
    return {
        "rule_id": "SSRF-001",
        "level": "error",
        "message": f"SSRF vulnerability: {reason}",
        "file_path": file_path,
        "line_number": line_number,
        "snippet": snippet,
        "details": {"url": url, "reason": reason},
    }


def create_unicode_finding(
    attack_type: str,
    details: str,
    file_path: Optional[str] = None,
    line_number: Optional[int] = None,
    snippet: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a SARIF finding for Unicode attack detection.

    Args:
        attack_type: Type of Unicode attack (zero-width, bidi, homoglyph, etc.)
        details: Details about the attack
        file_path: File where attack was found
        line_number: Line number in file
        snippet: Code snippet

    Returns:
        Finding dictionary for SARIF formatter
    """
    return {
        "rule_id": "UNICODE-001",
        "level": "error",
        "message": f"Unicode attack detected: {attack_type}",
        "file_path": file_path,
        "line_number": line_number,
        "snippet": snippet,
        "details": {"attack_type": attack_type, "details": details},
    }


def create_config_finding(
    pattern: str,
    reason: str,
    file_path: str,
    line_number: Optional[int] = None,
    snippet: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a SARIF finding for config file exfiltration.

    Args:
        pattern: The malicious pattern detected
        reason: Why this pattern is dangerous
        file_path: Config file path
        line_number: Line number in file
        snippet: Code snippet

    Returns:
        Finding dictionary for SARIF formatter
    """
    return {
        "rule_id": "CONFIG-001",
        "level": "error",
        "message": f"Config file exfiltration pattern: {reason}",
        "file_path": file_path,
        "line_number": line_number,
        "snippet": snippet,
        "details": {"pattern": pattern, "reason": reason},
    }


def create_secret_finding(
    secret_type: str,
    file_path: str,
    line_number: Optional[int] = None,
    snippet: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a SARIF finding for secret detection.

    Args:
        secret_type: Type of secret (GitHub token, AWS key, etc.)
        file_path: File containing secret
        line_number: Line number in file
        snippet: Code snippet (should be redacted)

    Returns:
        Finding dictionary for SARIF formatter
    """
    from ai_guardian.scanners.secret_types import get_secret_type_display

    return {
        "rule_id": "SECRET-001",
        "level": "error",
        "message": f"Secret detected: {get_secret_type_display(secret_type)}",
        "file_path": file_path,
        "line_number": line_number,
        "snippet": snippet,
        "details": {"secret_type": secret_type},
    }


def create_pii_finding(
    pii_type: str,
    file_path: str,
    line_number: Optional[int] = None,
    snippet: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "rule_id": "PII-001",
        "level": "warning",
        "message": f"PII detected: {pii_type}",
        "file_path": file_path,
        "line_number": line_number,
        "snippet": snippet,
        "details": {"pii_type": pii_type},
    }


def create_prompt_injection_finding(
    description: str,
    file_path: str,
    line_number: Optional[int] = None,
    snippet: Optional[str] = None,
    start_column: Optional[int] = None,
    end_column: Optional[int] = None,
) -> Dict[str, Any]:
    finding = {
        "rule_id": "PROMPT-INJECTION-001",
        "level": "warning",
        "message": f"Prompt injection detected: {description}",
        "file_path": file_path,
        "line_number": line_number,
        "snippet": snippet,
        "details": {"description": description},
    }
    if start_column is not None:
        finding["start_column"] = start_column
    if end_column is not None:
        finding["end_column"] = end_column
    return finding


def create_supply_chain_finding(
    category: str,
    reason: str,
    file_path: str,
    line_number: Optional[int] = None,
    snippet: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "rule_id": "SUPPLY-CHAIN-001",
        "level": "error",
        "message": f"Supply chain threat: {reason}",
        "file_path": file_path,
        "line_number": line_number,
        "snippet": snippet,
        "details": {"category": category, "reason": reason},
    }


def create_code_security_finding(
    rule_id: str,
    description: str,
    severity: str,
    confidence: str,
    file_path: str,
    line_number: Optional[int] = None,
    start_column: Optional[int] = None,
    snippet: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a finding dict for code security (Bandit) issues."""
    level = "error" if severity.upper() == "HIGH" else "warning"
    return {
        "rule_id": rule_id,
        "level": level,
        "message": f"Code security issue ({severity}): {description}",
        "file_path": file_path,
        "line_number": line_number,
        "start_column": start_column,
        "snippet": snippet,
        "details": {
            "severity": severity,
            "confidence": confidence,
            "scanner": "bandit",
        },
    }


def create_offensive_language_finding(
    rule_id: str,
    description: str,
    category: str,
    suggestion: str,
    file_path: str,
    line_number: Optional[int] = None,
    start_column: Optional[int] = None,
    matched_text: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a finding dict for offensive language detections."""
    return {
        "rule_id": rule_id,
        "level": "warning",
        "message": f"Offensive language ({category}): {description}",
        "file_path": file_path,
        "line_number": line_number,
        "start_column": start_column,
        "details": {
            "category": category,
            "suggestion": suggestion,
            "matched_text": matched_text or "",
        },
    }


def create_canary_detection_finding(
    token: str,
    description: str,
    file_path: str,
    line_number: Optional[int] = None,
    start_column: Optional[int] = None,
    matched_text: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a finding dict for canary token detections."""
    return {
        "rule_id": "canary_detected",
        "level": "error",
        "message": f"Canary token detected: {description!r}",
        "file_path": file_path,
        "line_number": line_number,
        "start_column": start_column,
        "details": {
            "token": token,
            "description": description,
            "matched_text": matched_text or "",
        },
    }


def create_exfil_detection_finding(
    category: str,
    reason: str,
    file_path: str,
    line_number: Optional[int] = None,
    start_column: Optional[int] = None,
    snippet: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a finding dict for exfil detection violations."""
    return {
        "rule_id": "EXFIL-DETECTION-001",
        "level": "error",
        "message": f"Credential exfiltration: {reason}",
        "file_path": file_path,
        "line_number": line_number,
        "start_column": start_column,
        "snippet": snippet,
        "details": {"category": category, "reason": reason},
    }
