"""
Output parsers for different scanner engines.

Provides a unified interface for parsing output from different secret scanners,
normalizing their output into a common format.
"""

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class ScannerOutputParser(ABC):
    """Abstract base class for scanner output parsers."""

    @abstractmethod
    def parse(self, output_file: str) -> Optional[Dict[str, Any]]:
        """
        Parse scanner output file into standardized format.

        Args:
            output_file: Path to scanner output file

        Returns:
            Standardized result dictionary with format:
            {
                "has_secrets": bool,
                "findings": [
                    {
                        "rule_id": str,
                        "file": str,
                        "line_number": int,
                        "description": str
                    },
                    ...
                ],
                "total_findings": int
            }
            Returns None if parsing fails.
        """
        pass


class GitleaksOutputParser(ScannerOutputParser):
    """
    Parser for Gitleaks and BetterLeaks output.

    Both tools use the same JSON format:
    [
        {
            "RuleID": "aws-access-token",
            "File": "test.txt",
            "StartLine": 5,
            "EndLine": 5,
            "Description": "AWS Access Key"
        },
        ...
    ]
    """

    def parse(self, output_file: str) -> Optional[Dict[str, Any]]:
        """
        Parse Gitleaks JSON output.

        Args:
            output_file: Path to Gitleaks JSON report

        Returns:
            Standardized result dict or None on error
        """
        try:
            output_path = Path(output_file)
            if not output_path.exists():
                logger.error(f"Gitleaks output file not found: {output_file}")
                return None

            with open(output_file, "r", encoding="utf-8") as f:
                findings = json.load(f)

            # Empty list means no secrets
            if not findings:
                return {"has_secrets": False, "findings": [], "total_findings": 0}

            # Convert to standardized format
            standardized_findings = []
            for finding in findings:
                standardized_findings.append(
                    {
                        "rule_id": finding.get("RuleID", "unknown"),
                        "file": finding.get("File", "unknown"),
                        "line_number": finding.get("StartLine", 0),
                        "end_line": finding.get("EndLine", 0),
                        "description": finding.get("Description", "Secret detected"),
                        "commit": finding.get("Commit", "N/A"),
                        "matched_text": finding.get("Match", ""),
                        "start_column": finding.get("StartColumn"),
                        "end_column": finding.get("EndColumn"),
                    }
                )

            return {
                "has_secrets": True,
                "findings": standardized_findings,
                "total_findings": len(standardized_findings),
            }

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Gitleaks JSON output: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error parsing Gitleaks output: {e}")
            return None


def _normalize_leaktk_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a single leaktk ScanResults finding to standardized format.

    Handles leaktk 0.3.x format with nested rule/location objects.
    Used by both LeakTKOutputParser (file-based) and listen mode (stdout).
    """
    rule = result.get("rule", {})
    location = result.get("location", {})
    start = location.get("start", {})
    end = location.get("end", {})
    return {
        "rule_id": rule.get("id", "unknown"),
        "file": location.get("path", "unknown"),
        "line_number": start.get("line", 0),
        "end_line": end.get("line", 0),
        "description": rule.get("description", "Secret detected"),
        "commit": location.get("version", "N/A"),
        "matched_text": result.get("match", ""),
        "start_column": start.get("column"),
        "end_column": end.get("column"),
    }


class LeakTKOutputParser(ScannerOutputParser):
    """
    Parser for LeakTK output.

    Supports two formats:
    - v0.3.x: {"kind":"ScanResults","results":[{"rule":{"id":...},"location":{...}}]}
    - Legacy:  {"findings":[{"RuleID":...,"StartLine":...}],"errors":[]}
    """

    def parse(self, output_file: str) -> Optional[Dict[str, Any]]:
        """
        Parse LeakTK JSON output.

        Args:
            output_file: Path to LeakTK JSON report

        Returns:
            Standardized result dict or None on error
        """
        try:
            output_path = Path(output_file)
            if not output_path.exists():
                logger.error(f"LeakTK output file not found: {output_file}")
                return None

            with open(output_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # v0.3.x format: {"kind":"ScanResults","results":[...]}
            if "results" in data:
                results = data["results"]
                if not results:
                    return {
                        "has_secrets": False,
                        "findings": [],
                        "total_findings": 0,
                    }
                standardized = [_normalize_leaktk_result(r) for r in results]
                return {
                    "has_secrets": True,
                    "findings": standardized,
                    "total_findings": len(standardized),
                }

            # Legacy format: {"findings":[...],"errors":[]}
            errors = data.get("errors", [])
            if errors:
                for error in errors:
                    logger.warning(f"LeakTK scanner error: {error}")

            findings = data.get("findings", [])
            if not findings:
                return {"has_secrets": False, "findings": [], "total_findings": 0}

            standardized_findings = []
            for finding in findings:
                standardized_findings.append(
                    {
                        "rule_id": finding.get("RuleID", "unknown"),
                        "file": finding.get("File", "unknown"),
                        "line_number": finding.get("StartLine", 0),
                        "end_line": finding.get("EndLine", 0),
                        "description": finding.get("Description", "Secret detected"),
                        "commit": finding.get("Commit", "N/A"),
                        "matched_text": finding.get("Match", ""),
                        "start_column": finding.get("StartColumn"),
                        "end_column": finding.get("EndColumn"),
                    }
                )

            return {
                "has_secrets": True,
                "findings": standardized_findings,
                "total_findings": len(standardized_findings),
            }

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LeakTK JSON output: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error parsing LeakTK output: {e}")
            return None


class TruffleHogOutputParser(ScannerOutputParser):
    """
    Parser for TruffleHog v3 output.

    TruffleHog outputs newline-delimited JSON with format:
    {"SourceMetadata":{"Data":{"Filesystem":{"file":"test.txt","line":5}}},"DetectorName":"AWS","DetectorType":2,"Verified":false}
    {"SourceMetadata":{"Data":{"Filesystem":{"file":"test.txt","line":10}}},"DetectorName":"GitHub","DetectorType":13,"Verified":false}
    """

    def parse(self, output_file: str) -> Optional[Dict[str, Any]]:
        """
        Parse TruffleHog newline-delimited JSON output.

        Args:
            output_file: Path to TruffleHog output file (newline-delimited JSON)

        Returns:
            Standardized result dict or None on error
        """
        try:
            output_path = Path(output_file)
            if not output_path.exists():
                logger.error(f"TruffleHog output file not found: {output_file}")
                return None

            standardized_findings = []

            with open(output_file, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        finding = json.loads(line)

                        # Extract file and line information from SourceMetadata
                        source_meta = (
                            finding.get("SourceMetadata", {})
                            .get("Data", {})
                            .get("Filesystem", {})
                        )
                        file_path = source_meta.get("file", "unknown")
                        line_number = source_meta.get("line", 0)

                        # Get detector information
                        detector_name = finding.get("DetectorName", "unknown")
                        verified = finding.get("Verified", False)

                        # Build description
                        description = f"{detector_name} secret detected"
                        if verified:
                            description += " (verified)"

                        standardized_findings.append(
                            {
                                "rule_id": detector_name.lower().replace(" ", "-"),
                                "file": file_path,
                                "line_number": line_number,
                                "end_line": line_number,
                                "description": description,
                                "commit": "N/A",
                                "verified": verified,
                            }
                        )

                    except json.JSONDecodeError as e:
                        logger.warning(
                            f"Failed to parse TruffleHog line {line_num}: {e}"
                        )
                        continue

            # No findings means no secrets
            if not standardized_findings:
                return {"has_secrets": False, "findings": [], "total_findings": 0}

            return {
                "has_secrets": True,
                "findings": standardized_findings,
                "total_findings": len(standardized_findings),
            }

        except Exception as e:
            logger.error(f"Unexpected error parsing TruffleHog output: {e}")
            return None


class DetectSecretsOutputParser(ScannerOutputParser):
    """
    Parser for detect-secrets output.

    detect-secrets outputs a baseline JSON file with format:
    {
        "results": {
            "test.txt": [
                {
                    "type": "AWS Access Key",
                    "line_number": 5,
                    "hashed_secret": "abc123..."
                }
            ]
        },
        "version": "1.0.0"
    }
    """

    def parse(self, output_file: str) -> Optional[Dict[str, Any]]:
        """
        Parse detect-secrets baseline JSON output.

        Args:
            output_file: Path to detect-secrets baseline file

        Returns:
            Standardized result dict or None on error
        """
        try:
            output_path = Path(output_file)
            if not output_path.exists():
                logger.error(f"detect-secrets output file not found: {output_file}")
                return None

            with open(output_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Get results
            results = data.get("results", {})

            # No results means no secrets
            if not results:
                return {"has_secrets": False, "findings": [], "total_findings": 0}

            # Convert to standardized format
            standardized_findings = []
            for file_path, file_findings in results.items():
                for finding in file_findings:
                    secret_type = finding.get("type", "unknown")
                    line_number = finding.get("line_number", 0)

                    standardized_findings.append(
                        {
                            "rule_id": secret_type.lower().replace(" ", "-"),
                            "file": file_path,
                            "line_number": line_number,
                            "end_line": line_number,
                            "description": f"{secret_type} detected",
                            "commit": "N/A",
                        }
                    )

            return {
                "has_secrets": True,
                "findings": standardized_findings,
                "total_findings": len(standardized_findings),
            }

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse detect-secrets JSON output: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error parsing detect-secrets output: {e}")
            return None


class SecretlintOutputParser(ScannerOutputParser):
    """
    Parser for Secretlint output.

    Secretlint outputs JSON array of file results:
    [
        {
            "filePath": "/path/to/file.txt",
            "messages": [
                {
                    "ruleId": "@secretlint/secretlint-rule-preset-recommend > @secretlint/secretlint-rule-aws",
                    "message": "Found AWS Access Key ID",
                    "loc": {"start": {"line": 3, "column": 0}, "end": {"line": 3, "column": 42}},
                    "severity": "error"
                }
            ]
        }
    ]

    Also handles newline-delimited JSON (one object per file).
    """

    def parse(self, output_file: str) -> Optional[Dict[str, Any]]:
        try:
            output_path = Path(output_file)
            if not output_path.exists():
                logger.error(f"Secretlint output file not found: {output_file}")
                return None

            content = output_path.read_text(encoding="utf-8").strip()
            if not content:
                return {"has_secrets": False, "findings": [], "total_findings": 0}

            file_results = self._parse_content(content)
            if file_results is None:
                return None

            standardized_findings = []
            for file_result in file_results:
                file_path = file_result.get("filePath", "unknown")
                for msg in file_result.get("messages", []):
                    rule_id = self._normalize_rule_id(msg.get("ruleId", "unknown"))
                    loc = msg.get("loc", {})
                    start = loc.get("start", {})
                    end = loc.get("end", {})

                    standardized_findings.append(
                        {
                            "rule_id": rule_id,
                            "file": file_path,
                            "line_number": start.get("line", 0),
                            "end_line": end.get("line", start.get("line", 0)),
                            "description": msg.get("message", "Secret detected"),
                            "commit": "N/A",
                            "start_column": start.get("column"),
                            "end_column": end.get("column"),
                        }
                    )

            if not standardized_findings:
                return {"has_secrets": False, "findings": [], "total_findings": 0}

            return {
                "has_secrets": True,
                "findings": standardized_findings,
                "total_findings": len(standardized_findings),
            }

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Secretlint JSON output: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error parsing Secretlint output: {e}")
            return None

    @staticmethod
    def _parse_content(content: str) -> Optional[List[Dict]]:
        try:
            data = json.loads(content)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return [data]
            return None
        except json.JSONDecodeError:
            pass  # intentionally silent — best-effort operation

        results = []
        for line in content.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    results.append(obj)
            except json.JSONDecodeError:
                continue
        return results if results else None

    @staticmethod
    def _normalize_rule_id(rule_id: str) -> str:
        if " > " in rule_id:
            rule_id = rule_id.split(" > ")[-1]
        rule_id = rule_id.replace("@secretlint/secretlint-rule-", "")
        return rule_id


class GitGuardianOutputParser(ScannerOutputParser):
    """
    Parser for GitGuardian (ggshield) output.

    ggshield outputs JSON with format:
    {
        "policy_break_count": 1,
        "policies": ["Secrets detection"],
        "policy_breaks": [
            {
                "break_type": "AWS Keys",
                "policy": "Secrets detection",
                "validity": "valid_data",
                "incidents": [
                    {
                        "location": {
                            "filename": "test.txt",
                            "line_start": 5,
                            "line_end": 5
                        },
                        "type": "aws_access_key_id"
                    }
                ]
            }
        ]
    }
    """

    def parse(self, output_file: str) -> Optional[Dict[str, Any]]:
        try:
            output_path = Path(output_file)
            if not output_path.exists():
                logger.error(f"GitGuardian output file not found: {output_file}")
                return None

            with open(output_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            policy_breaks = data.get("policy_breaks", [])
            if not policy_breaks:
                return {"has_secrets": False, "findings": [], "total_findings": 0}

            standardized_findings = []
            for pb in policy_breaks:
                break_type = pb.get("break_type", "unknown")
                validity = pb.get("validity", "")
                verified = validity == "valid_data"

                for incident in pb.get("incidents", []):
                    location = incident.get("location", {})
                    incident_type = incident.get("type", break_type)

                    standardized_findings.append(
                        {
                            "rule_id": incident_type.lower().replace(" ", "-"),
                            "file": location.get("filename", "unknown"),
                            "line_number": location.get("line_start", 0),
                            "end_line": location.get("line_end", 0),
                            "description": f"{break_type} detected",
                            "commit": "N/A",
                            "verified": verified,
                            "start_column": location.get("column_start"),
                            "end_column": location.get("column_end"),
                        }
                    )

            if not standardized_findings:
                return {"has_secrets": False, "findings": [], "total_findings": 0}

            return {
                "has_secrets": True,
                "findings": standardized_findings,
                "total_findings": len(standardized_findings),
            }

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse GitGuardian JSON output: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error parsing GitGuardian output: {e}")
            return None


# Parser registry
OUTPUT_PARSERS = {
    "gitleaks": GitleaksOutputParser(),
    "leaktk": LeakTKOutputParser(),
    "trufflehog": TruffleHogOutputParser(),
    "detect-secrets": DetectSecretsOutputParser(),
    "secretlint": SecretlintOutputParser(),
    "gitguardian": GitGuardianOutputParser(),
}


def get_parser(parser_name: str) -> ScannerOutputParser:
    """
    Get parser instance by name.

    Args:
        parser_name: Name of parser ('gitleaks' or 'leaktk')

    Returns:
        Parser instance

    Raises:
        ValueError: If parser name is unknown
    """
    if parser_name not in OUTPUT_PARSERS:
        raise ValueError(
            f"Unknown parser: {parser_name}. "
            f"Available parsers: {', '.join(OUTPUT_PARSERS.keys())}"
        )
    return OUTPUT_PARSERS[parser_name]
