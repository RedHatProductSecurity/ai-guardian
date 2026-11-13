"""
Universal ScanResult dataclass for all violation scanners.

Phase 1 of scanner registry refactor (#1251). Standardizes output format
across all scanner types without changing scanner internals.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import uuid4


def generate_violation_id() -> str:
    """Generate a unique violation ID: ``viol_`` + 8-char hex."""
    return "viol_" + uuid4().hex[:8]


@dataclass
class ScanResult:
    """Universal result from any violation scanner.

    All scanners return a ScanResult at their call sites in hook_processing.py.
    Scanner internals are unchanged — wrapping happens after the call returns.
    """

    detected: bool
    violation_type: str
    id: Optional[str] = None
    severity: str = "high"
    should_block: bool = True
    error_message: str = ""
    matched_text: str = ""
    matched_pattern: str = ""
    rule_id: str = ""
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    end_line: Optional[int] = None
    start_column: Optional[int] = None
    end_column: Optional[int] = None
    engine: str = ""
    config_section: str = ""
    attack_type: str = ""
    confidence: float = 0.0
    total_findings: int = 1
    findings: Optional[List[Any]] = None
    redacted_content: Optional[str] = None
    redactions: Optional[List[Dict[str, Any]]] = None
    scan_time_ms: float = 0.0
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.detected and self.id is None:
            self.id = generate_violation_id()

    @classmethod
    def clean(cls, violation_type: str, **kwargs) -> "ScanResult":
        """Create a no-detection result."""
        return cls(
            detected=False,
            violation_type=violation_type,
            should_block=False,
            severity="none",
            **kwargs,
        )

    @classmethod
    def from_secret_scan(
        cls,
        has_secrets: bool,
        error_message: Optional[str],
        engine: str = "",
        matched_text: str = "",
        line_number: Optional[int] = None,
        start_column: Optional[int] = None,
        findings: Optional[list] = None,
        scan_time_ms: float = 0.0,
        file_path: Optional[str] = None,
    ) -> "ScanResult":
        """Wrap secret scanner (check_secrets) result."""
        return cls(
            detected=has_secrets,
            violation_type="secret_detected",
            should_block=has_secrets,
            error_message=error_message or "",
            engine=engine,
            matched_text=matched_text,
            line_number=line_number,
            start_column=start_column,
            findings=findings,
            total_findings=len(findings) if findings else (1 if has_secrets else 0),
            scan_time_ms=scan_time_ms,
            file_path=file_path,
        )

    @classmethod
    def from_pii_scan(
        cls,
        has_pii: bool,
        redacted_text: Optional[str],
        redactions: Optional[list],
        warning_message: Optional[str],
        file_path: Optional[str] = None,
    ) -> "ScanResult":
        """Wrap PII scanner (_scan_for_pii) result."""
        return cls(
            detected=has_pii,
            violation_type="pii_detected",
            should_block=has_pii,
            error_message=warning_message or "",
            redacted_content=redacted_text,
            redactions=redactions,
            total_findings=len(redactions) if redactions else (1 if has_pii else 0),
            config_section="pii_scanning",
            file_path=file_path,
        )

    @classmethod
    def from_prompt_injection(
        cls,
        should_block: bool,
        error_message: Optional[str],
        detected: bool,
        matched_text: str = "",
        matched_pattern: str = "",
        line_number: Optional[int] = None,
        start_column: Optional[int] = None,
        end_column: Optional[int] = None,
        confidence: float = 0.0,
        findings: Optional[list] = None,
        attack_type: str = "",
        file_path: Optional[str] = None,
    ) -> "ScanResult":
        """Wrap prompt injection detector result."""
        vtype = (
            "jailbreak_detected" if attack_type == "jailbreak" else "prompt_injection"
        )
        return cls(
            detected=detected,
            violation_type=vtype,
            should_block=should_block,
            error_message=error_message or "",
            matched_text=matched_text,
            matched_pattern=matched_pattern,
            line_number=line_number,
            start_column=start_column,
            end_column=end_column,
            confidence=confidence,
            findings=findings,
            total_findings=len(findings) if findings else (1 if detected else 0),
            config_section="prompt_injection",
            attack_type=attack_type,
            file_path=file_path,
        )

    @classmethod
    def from_ssrf_check(
        cls,
        is_ssrf: bool,
        reason: str,
        is_immutable: bool,
        matched_text: str = "",
    ) -> "ScanResult":
        """Wrap SSRF protector (_check_url) result."""
        return cls(
            detected=is_ssrf,
            violation_type="ssrf_blocked",
            should_block=is_ssrf,
            error_message=reason,
            matched_text=matched_text,
            config_section="ssrf_protection",
            extra={"is_immutable": is_immutable},
        )

    @classmethod
    def from_config_exfil(
        cls,
        should_block: bool,
        error_message: Optional[str],
        details: Optional[Dict[str, Any]],
        file_path: Optional[str] = None,
    ) -> "ScanResult":
        """Wrap config exfil scanner result."""
        matched_text = ""
        matched_pattern = ""
        line_number = None
        start_column = None
        end_column = None
        findings = None
        if details:
            matched_text = details.get("matched_text", "")
            matched_pattern = details.get("pattern", "")
            line_number = details.get("line_number")
            start_column = details.get("start_column")
            end_column = details.get("end_column")
            findings = details.get("findings")
        return cls(
            detected=should_block or bool(details),
            violation_type="config_file_exfil",
            should_block=should_block,
            error_message=error_message or "",
            matched_text=matched_text,
            matched_pattern=matched_pattern,
            line_number=line_number,
            start_column=start_column,
            end_column=end_column,
            findings=findings,
            config_section="config_exfil",
            file_path=file_path,
            extra={
                "is_immutable": bool(details and details.get("is_immutable") is True)
            },
        )

    @classmethod
    def from_context_poisoning(
        cls,
        should_block: bool,
        error_message: Optional[str],
        detected: bool,
        matched_text: str = "",
        matched_pattern: str = "",
        line_number: Optional[int] = None,
        start_column: Optional[int] = None,
        end_column: Optional[int] = None,
        confidence: float = 0.0,
        findings: Optional[list] = None,
    ) -> "ScanResult":
        """Wrap context poisoning detector result."""
        return cls(
            detected=detected,
            violation_type="context_poisoning",
            should_block=should_block,
            error_message=error_message or "",
            matched_text=matched_text,
            matched_pattern=matched_pattern,
            line_number=line_number,
            start_column=start_column,
            end_column=end_column,
            confidence=confidence,
            findings=findings,
            total_findings=len(findings) if findings else (1 if detected else 0),
            config_section="context_poisoning",
        )

    @classmethod
    def from_supply_chain(
        cls,
        should_block: bool,
        error_message: Optional[str],
        details: Optional[Dict[str, Any]],
        file_path: Optional[str] = None,
    ) -> "ScanResult":
        """Wrap supply chain scanner result."""
        matched_text = ""
        matched_pattern = ""
        category = ""
        line_number = None
        start_column = None
        end_column = None
        findings = None
        if details:
            matched_text = details.get("matched_text", "")
            matched_pattern = details.get("pattern", "")
            category = details.get("category", "")
            line_number = details.get("line_number")
            start_column = details.get("start_column")
            end_column = details.get("end_column")
            findings = details.get("findings")
        return cls(
            detected=should_block or bool(details),
            violation_type="supply_chain",
            should_block=should_block,
            error_message=error_message or "",
            matched_text=matched_text,
            matched_pattern=matched_pattern,
            line_number=line_number,
            start_column=start_column,
            end_column=end_column,
            findings=findings,
            config_section="supply_chain",
            attack_type=category,
            file_path=file_path,
        )

    @classmethod
    def from_exfil_detection(
        cls,
        should_block: bool,
        error_message: Optional[str],
        details: Optional[Dict[str, Any]],
    ) -> "ScanResult":
        """Wrap exfil detection scanner result."""
        matched_text = ""
        matched_pattern = ""
        category = ""
        line_number = None
        start_column = None
        end_column = None
        findings = None
        if details:
            matched_text = details.get("matched_text", "")
            matched_pattern = details.get("pattern", "")
            category = details.get("category", "")
            line_number = details.get("line_number")
            start_column = details.get("start_column")
            end_column = details.get("end_column")
            findings = details.get("findings")
        return cls(
            detected=should_block or bool(details),
            violation_type="exfil_detection",
            should_block=should_block,
            error_message=error_message or "",
            matched_text=matched_text,
            matched_pattern=matched_pattern,
            line_number=line_number,
            start_column=start_column,
            end_column=end_column,
            findings=findings,
            config_section="exfil_detection",
            attack_type=category,
        )

    @classmethod
    def from_offensive_language(
        cls,
        findings: List[Dict[str, Any]],
        action: str = "log",
        file_path: Optional[str] = None,
    ) -> "ScanResult":
        """Wrap offensive language scanner result."""
        detected = bool(findings)
        should_block = detected and action == "block"
        first = findings[0] if findings else {}
        return cls(
            detected=detected,
            violation_type="offensive_language",
            should_block=should_block,
            error_message=(
                f"Offensive language detected: {first.get('description', '')}"
                if detected
                else ""
            ),
            matched_text=first.get("matched_text", ""),
            matched_pattern=first.get("rule_id", ""),
            rule_id=first.get("rule_id", ""),
            line_number=first.get("line_number"),
            start_column=first.get("start_column"),
            end_column=first.get("end_column"),
            findings=findings,
            total_findings=len(findings),
            config_section="scan_offensive",
            attack_type=first.get("category_tag", ""),
            file_path=file_path,
            extra={"action": action},
        )

    @classmethod
    def from_canary_detection(
        cls,
        should_block: bool,
        error_message: Optional[str],
        details: Optional[Dict[str, Any]],
        source: Optional[str] = None,
    ) -> "ScanResult":
        """Wrap canary token detector result."""
        matched_text = ""
        matched_token = ""
        description = ""
        line_number = None
        start_column = None
        end_column = None
        if details:
            matched_text = details.get("matched_text", "")
            matched_token = details.get("token", "")
            description = details.get("description", "")
            line_number = details.get("line_number")
            start_column = details.get("start_column")
            end_column = details.get("end_column")
        return cls(
            detected=should_block or bool(details),
            violation_type="canary_detected",
            should_block=should_block,
            error_message=error_message or "",
            matched_text=matched_text,
            matched_pattern=matched_token,
            line_number=line_number,
            start_column=start_column,
            end_column=end_column,
            config_section="canary_detection",
            attack_type=description,
            file_path=source,
        )

    def to_blocked_dict(
        self,
        *,
        source: str = "",
        extra_fields: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build a standard violation ``blocked`` dict from this result's fields."""
        blocked: Dict[str, Any] = {}
        if self.id:
            blocked["violation_id"] = self.id
        if self.file_path:
            blocked["file_path"] = self.file_path
        if self.line_number is not None:
            blocked["line_number"] = self.line_number
        if self.start_column is not None:
            blocked["start_column"] = self.start_column
        if self.end_column is not None:
            blocked["end_column"] = self.end_column
        if self.violation_type == "suspected_password":
            # Never use partial-hint redaction or surrounding text for suspected
            # passwords, even if a future caller accidentally supplies a match.
            blocked["reason"] = (
                "Password-likelihood analysis incomplete; protection is not assured."
                if self.extra.get("incomplete")
                else "Suspected password-like content (heuristic; not a confirmed secret)."
            )
            blocked["action"] = "block" if self.should_block else "warn"
            blocked["findings"] = self.findings or []
            blocked["total_findings"] = self.total_findings
            return blocked
        if self.violation_type == "command_credential_detected":
            # Command arguments are private input. Persist only fixed labels and
            # bounded integer locations, never values, command text, or snippets.
            allowed_classes = {
                "inline_literal",
                "credential_reference",
                "interactive_no_value_authentication",
                "unsupported_or_incomplete_parse",
            }
            allowed_families = {"curl", "wget", "powershell-web", "unknown"}
            allowed_options = {
                "--user",
                "--proxy-user",
                "--oauth2-bearer",
                "--header",
                "--proxy-header",
                "--netrc-file",
                "--config",
                "--netrc",
                "--netrc-optional",
                "--password",
                "--http-user",
                "--http-password",
                "--ftp-user",
                "--ftp-password",
                "--password-file",
                "--ask-password",
                "--use-askpass",
                "-u",
                "-U",
                "-H",
                "-K",
                "-Headers",
                "-Token",
                "-BearerToken",
                "-Credential",
                "url-userinfo",
                "ConvertTo-SecureString -AsPlainText",
                "unsupported-wrapper",
                "unsupported-syntax",
                "command-size-limit",
                "parser-failure",
            }
            safe_findings = []
            safe_classes: set[str] = set()
            for finding in self.findings or []:
                if not isinstance(finding, dict):
                    continue
                command_index = finding.get("command_index")
                argument_index = finding.get("argument_index")
                finding_class = finding.get("finding_class")
                if type(command_index) is not int or type(argument_index) is not int:
                    continue
                if command_index < 0 or argument_index < 0:
                    continue
                if (
                    not isinstance(finding_class, str)
                    or finding_class not in allowed_classes
                ):
                    continue
                safe_classes.add(finding_class)
                family = finding.get("command_family")
                option = finding.get("option")
                safe_findings.append(
                    {
                        "command_index": command_index,
                        "argument_index": argument_index,
                        "command_family": (
                            family
                            if isinstance(family, str) and family in allowed_families
                            else "unknown"
                        ),
                        "option": (
                            option
                            if isinstance(option, str) and option in allowed_options
                            else "unsupported-option"
                        ),
                        "finding_class": finding_class,
                    }
                )
            classes = sorted(safe_classes)
            reason = (
                "Inline credential argument detected; value withheld."
                if "inline_literal" in classes
                else (
                    "Command credential analysis incomplete; no credential confirmed."
                    if "unsupported_or_incomplete_parse" in classes
                    else "Credential reference or interactive authentication; no literal value found."
                )
            )
            blocked["reason"] = reason
            blocked["action"] = (
                self.extra.get("action")
                if isinstance(self.extra.get("action"), str)
                and self.extra.get("action")
                in {"block", "ask", "warn", "log-only", "allow"}
                else "block" if self.should_block else "warn"
            )
            blocked["finding_classes"] = classes
            blocked["findings"] = safe_findings
            blocked["total_findings"] = len(safe_findings)
            return blocked
        if self.violation_type == "http_request_credential_detected":
            # Source text and credential literals are private. Persist only
            # allowlisted sink/client labels and bounded line locations.
            allowed_classes = {
                "inline_literal",
                "unsupported_or_incomplete_analysis",
            }
            allowed_clients = {
                "requests",
                "httpx",
                "aiohttp",
                "urllib.request",
                "fetch",
                "axios",
                "http",
                "https",
                "xhr",
                "unknown",
            }
            allowed_sinks = {
                "authentication",
                "authorization_header",
                "api_key_header",
                "cookie_header",
                "url_userinfo",
                "url_userinfo",
                "password_field",
                "token_field",
                "api_key_field",
                "secret_field",
                "credential_field",
                "unknown",
            }
            safe_findings = []
            http_classes: set[str] = set()
            for finding in self.findings or []:
                if not isinstance(finding, dict):
                    continue
                line_number = finding.get("line_number")
                finding_class = finding.get("finding_class")
                if line_number is not None and (
                    type(line_number) is not int or line_number < 1
                ):
                    continue
                if (
                    not isinstance(finding_class, str)
                    or finding_class not in allowed_classes
                ):
                    continue
                http_classes.add(finding_class)
                client = finding.get("client")
                sink = finding.get("sink")
                safe_findings.append(
                    {
                        "line_number": line_number,
                        "client": (
                            client
                            if isinstance(client, str) and client in allowed_clients
                            else "unknown"
                        ),
                        "sink": (
                            sink
                            if isinstance(sink, str) and sink in allowed_sinks
                            else "unknown"
                        ),
                        "finding_class": finding_class,
                    }
                )
            blocked["reason"] = (
                "Hard-coded HTTP request credential detected; source values withheld."
                if "inline_literal" in http_classes
                else "HTTP request credential analysis incomplete; no credential confirmed."
            )
            blocked["action"] = (
                self.extra.get("action")
                if isinstance(self.extra.get("action"), str)
                and self.extra.get("action")
                in {"block", "ask", "warn", "log-only", "allow"}
                else "block" if self.should_block else "warn"
            )
            blocked["finding_classes"] = sorted(http_classes)
            blocked["findings"] = safe_findings
            blocked["total_findings"] = len(safe_findings)
            return blocked
        if self.matched_text:
            from ai_guardian.violations.redact import (
                REDACT_VIOLATION_TYPES,
                redact_secret_hint,
            )

            if self.violation_type in REDACT_VIOLATION_TYPES:
                if not (self.file_path and self.line_number is not None):
                    blocked["pattern_hint"] = redact_secret_hint(self.matched_text)
            else:
                blocked["matched_text"] = self.matched_text[:100]
        if self.matched_pattern:
            blocked["pattern"] = self.matched_pattern
        if self.rule_id:
            blocked["rule_id"] = self.rule_id
        if self.attack_type:
            blocked["category"] = self.attack_type
        if self.confidence:
            blocked["confidence"] = self.confidence
        if self.total_findings and self.total_findings > 1:
            blocked["total_findings"] = self.total_findings
        if self.error_message:
            blocked["reason"] = self.error_message
        blocked["action"] = "block" if self.should_block else "warn"
        if source:
            blocked["source"] = source
        if extra_fields:
            blocked.update(extra_fields)
        if "is_immutable" in self.extra:
            blocked["is_immutable"] = self.extra["is_immutable"] is True
        return blocked

    @classmethod
    def from_directory_rules(
        cls,
        decision: Optional[str],
        action: Optional[str],
        matched_pattern: Optional[str],
        file_path: Optional[str] = None,
        is_immutable: bool = False,
    ) -> "ScanResult":
        """Wrap directory rules check result."""
        blocked = decision == "deny"
        extra: Dict[str, Any] = {"decision": decision, "action": action}
        if is_immutable is True:
            extra["is_immutable"] = True
        return cls(
            detected=blocked,
            violation_type="directory_blocking",
            should_block=blocked and action == "block",
            error_message=(
                f"Directory access denied: {matched_pattern}" if blocked else ""
            ),
            matched_pattern=matched_pattern or "",
            config_section="directory_rules",
            file_path=file_path,
            extra=extra,
        )
