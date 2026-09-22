"""
Exfiltration Behavior Detection Scanner

Detects bash commands and shell scripts that steal credentials: curl/wget with
token vars, base64 encoding of secrets, cat of key files piped to network tools,
and environment variable collection via subshell. Complements config_file_scanning
with broader coverage of credential-theft behavior patterns.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from ai_guardian.config.utils import is_feature_enabled

logger = logging.getLogger(__name__)

_SHELL_EXTENSIONS = {".sh", ".bash", ".zsh", ".ksh", ".fish"}

_PATTERN_CATEGORIES = {
    "credential_theft": [
        (
            r"\bcurl\b.*\$\{?[A-Z_][A-Z0-9_]*(?:TOKEN|KEY|SECRET|PASSWORD|PASSWD|CRED|AUTH|API|BEARER|APIKEY|ACCESS)[A-Z0-9_]*\}?",
            "curl with credential env variable",
        ),
        (
            r"\bwget\b.*\$\{?[A-Z_][A-Z0-9_]*(?:TOKEN|KEY|SECRET|PASSWORD|PASSWD|CRED|AUTH|API|BEARER|APIKEY|ACCESS)[A-Z0-9_]*\}?",
            "wget with credential env variable",
        ),
        (
            r'\bcurl\b.*-H\s+["\']?Authorization:\s*\$',
            "curl Authorization header with variable",
        ),
        (
            r'\bcurl\b.*-H\s+["\']?X-Api-Key:\s*\$',
            "curl API key header with variable",
        ),
        (
            r'\bwget\b.*--header[=\s]+["\']?Authorization:\s*\$',
            "wget Authorization header with variable",
        ),
        (
            r"\bcurl\b.*--data.*\$\{?[A-Z_][A-Z0-9_]*(?:TOKEN|KEY|SECRET|PASSWORD|PASSWD|CRED|AUTH|API|BEARER)[A-Z0-9_]*\}?",
            "curl POST data with credential variable",
        ),
    ],
    "env_collection": [
        (r"\benv\b\s*\|.*\b(?:nc|netcat|ncat|socat)\b", "env piped to netcat"),
        (
            r"\benv\b\s*\|.*\b(?:python3?|ruby|perl|php)\b",
            "env piped to interpreter",
        ),
        (r"\bprintenv\b.*\|.*\b(?:nc|netcat|ncat|socat)\b", "printenv piped to netcat"),
        (
            r"\bprintenv\b.*\|.*\b(?:python3?|ruby|perl)\b",
            "printenv piped to interpreter",
        ),
        (
            r"\bset\b\s*\|.*\b(?:curl|wget|nc|netcat|socat)\b",
            "shell vars dumped to network",
        ),
        (r"\$\(\s*env\b", "env in command substitution"),
        (r"`\s*env\b", "env in backtick substitution"),
        (r"\$\(\s*printenv\b", "printenv in command substitution"),
        (
            r"\bexport\b.*\|.*\b(?:curl|wget|nc)\b",
            "exported vars piped to network",
        ),
    ],
    "key_file_exfil": [
        (
            r"\bcat\b.*\b(?:id_rsa|id_ed25519|id_ecdsa|id_dsa|\.pem|\.key|\.p12|\.pfx)\b.*\|.*\b(?:curl|wget|nc|netcat|ncat|socat|python3?|ruby)\b",
            "SSH/TLS key file piped to network",
        ),
        (
            r"\bcat\b.*(?:\.aws/credentials|\.aws/config)\b.*\|",
            "AWS credentials file piped to network",
        ),
        (
            r"\bcat\b.*(?:\.config/gcloud|gcloud/credentials)\b.*\|",
            "GCP credentials file piped to network",
        ),
        (
            r"\bcat\b.*\b(?:\.env|\.netrc|\.npmrc|\.pypirc|\.gitconfig)\b.*\|.*\b(?:curl|wget|nc|netcat|ncat|socat)\b",
            "credential config file piped to network",
        ),
        (
            r"\btar\b.*\.ssh\b.*\|.*\b(?:curl|wget|nc)\b",
            "SSH directory archived and sent to network",
        ),
        (
            r"\bscp\b.*\b(?:id_rsa|\.pem|\.key|credentials)\b.*@",
            "key file copied via scp to remote host",
        ),
    ],
    "base64_encoding": [
        (
            r"\bcat\b.*\b(?:id_rsa|id_ed25519|\.pem|\.key|\.p12)\b.*\|.*\bbase64\b",
            "SSH/TLS key base64 encoded",
        ),
        (
            r"\bcat\b.*(?:\.aws/credentials|credentials)\b.*\|.*\bbase64\b",
            "credentials file base64 encoded",
        ),
        (
            r"\bbase64\b[^|]*\b(?:id_rsa|id_ed25519|\.pem|\.key|credentials|\.env)\b",
            "base64 encoding of credential file",
        ),
        (
            r"\bpython3?\b.*\bbase64\.b64encode\b.*\b(?:open|read)\b.*\b(?:\.pem|\.key|id_rsa|credentials)\b",
            "python base64 encoding of credential file",
        ),
    ],
    "cloud_credential_exfil": [
        (
            r"\bcurl\b.*169\.254\.169\.254",
            "AWS/Azure IMDS metadata endpoint access",
        ),
        (
            r"\bcurl\b.*metadata\.google\.internal",
            "GCP metadata endpoint access",
        ),
        (
            r"\baws\s+sts\s+get-caller-identity\b.*\|.*\b(?:curl|wget|nc)\b",
            "AWS identity sent to network",
        ),
        (
            r"\baws\s+configure\s+(?:get|list)\b.*\|.*\b(?:curl|wget|nc)\b",
            "AWS config sent to network",
        ),
        (
            r"\bcat\b.*(?:\.azure|\.kube/config)\b.*\|",
            "Azure/Kubernetes credentials file piped to network",
        ),
    ],
    "secret_collection": [
        (
            r"\bcat\b.*\.netrc\b.*\|.*\b(?:curl|wget|nc|netcat)\b",
            ".netrc credentials piped to network",
        ),
        (
            r"\bcat\b.*\.npmrc\b.*\|.*\b(?:curl|wget|nc)\b",
            ".npmrc token piped to network",
        ),
        (
            r"\bcat\b.*\.pypirc\b.*\|.*\b(?:curl|wget|nc)\b",
            ".pypirc credentials piped to network",
        ),
        (
            r"\bgpg\b.*--export(?:-secret-keys)?\b.*\|.*\b(?:curl|wget|nc|netcat)\b",
            "GPG key exported to network",
        ),
        (
            r"\bsecurity\s+find-(?:generic|internet)-password\b.*-w\b",
            "macOS keychain password extracted",
        ),
        (
            r"\baws\s+secretsmanager\s+get-secret-value\b.*\|.*\b(?:curl|wget|nc)\b",
            "AWS Secrets Manager value sent to network",
        ),
    ],
}

_compiled_patterns: Optional[Dict[str, List[Tuple[re.Pattern, str]]]] = None


def _compile_patterns() -> Dict[str, List[Tuple[re.Pattern, str]]]:
    global _compiled_patterns
    if _compiled_patterns is not None:
        return _compiled_patterns

    try:
        from ai_guardian.patterns import load_bundled_rules

        def _transform(raw_rules):
            by_group: Dict[str, List[Tuple[re.Pattern, str]]] = {}
            for rule in raw_rules:
                group = rule.get("group", "unknown")
                regex = rule.get("regex", "")
                desc = rule.get("description", "")
                if regex:
                    try:
                        compiled = re.compile(regex, re.IGNORECASE)
                        by_group.setdefault(group, []).append((compiled, desc))
                    except re.error:
                        logger.warning("Invalid exfil detection pattern: %s", regex)
            return by_group

        result: Dict[str, List[Tuple[re.Pattern, str]]] = load_bundled_rules(
            "exfil_detection", _transform, {}, "Exfil detection scanner"
        )
        if result:
            _compiled_patterns = result
            return _compiled_patterns
    except Exception as e:
        logger.debug("TOML load failed, using hardcoded patterns: %s", e)

    _compiled_patterns = {}
    for category, patterns in _PATTERN_CATEGORIES.items():
        compiled = []
        for regex, desc in patterns:
            try:
                compiled.append((re.compile(regex, re.IGNORECASE), desc))
            except re.error:
                logger.warning("Invalid hardcoded exfil detection pattern: %s", regex)
        _compiled_patterns[category] = compiled
    return _compiled_patterns


def _is_shell_script(file_path: str) -> bool:
    if not file_path:
        return False
    lower = file_path.lower()
    for ext in _SHELL_EXTENSIONS:
        if lower.endswith(ext):
            return True
    return False


class ExfilDetectionScanner:
    """Detects credential exfiltration behavior in bash commands and shell scripts."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        config = config or {}
        self.enabled = config.get("enabled", True)
        if isinstance(self.enabled, dict):
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc)
            self.enabled = is_feature_enabled(self.enabled, now, default=True)

        self.action = config.get("action", "block")

        raw_allowlist = config.get("allowlist_patterns", [])
        self.allowlist_patterns: List[re.Pattern] = []
        for pattern in raw_allowlist:
            if isinstance(pattern, str) and pattern:
                try:
                    self.allowlist_patterns.append(re.compile(pattern, re.IGNORECASE))
                except re.error:
                    logger.warning(
                        "Invalid exfil detection allowlist pattern: %s", pattern
                    )

        self.last_matched_pattern: Optional[str] = None
        self.last_matched_text: Optional[str] = None
        self.last_category: Optional[str] = None
        self.last_line_number: Optional[int] = None
        self.last_start_column: Optional[int] = None
        self.last_end_column: Optional[int] = None
        self.findings: List[Dict[str, Any]] = []

    def _is_allowlisted(self, command: str) -> bool:
        for pattern in self.allowlist_patterns:
            if pattern.search(command):
                return True
        return False

    def check_command(
        self, command: str
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """Scan a bash command for credential exfiltration patterns.

        Primary entry point for PreToolUse Bash hook.

        Returns:
            (should_block, error_message, details)
        """
        self.last_matched_pattern = None
        self.last_matched_text = None
        self.last_category = None
        self.last_line_number = None
        self.last_start_column = None
        self.last_end_column = None
        self.findings = []

        if not self.enabled or not command or not command.strip():
            return False, None, None

        if self._is_allowlisted(command):
            return False, None, None

        patterns = _compile_patterns()
        return self._match_patterns(
            command, "bash_command", patterns, list(_PATTERN_CATEGORIES.keys())
        )

    def scan(
        self, content: str, label: str = "shell_script"
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """Scan file content for credential exfiltration patterns.

        For batch scan of .sh, .bash, .zsh files.

        Returns:
            (should_block, error_message, details)
        """
        self.last_matched_pattern = None
        self.last_matched_text = None
        self.last_category = None
        self.last_line_number = None
        self.last_start_column = None
        self.last_end_column = None
        self.findings = []

        if not self.enabled or not content or not content.strip():
            return False, None, None

        patterns = _compile_patterns()
        return self._match_patterns(
            content, label, patterns, list(_PATTERN_CATEGORIES.keys())
        )

    def _match_patterns(
        self,
        content: str,
        label: str,
        patterns: Dict[str, List[Tuple[re.Pattern, str]]],
        categories: List[str],
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        lines = content.split("\n")

        for category in categories:
            category_patterns = patterns.get(category, [])
            for compiled_re, description in category_patterns:
                match = compiled_re.search(content)
                if match:
                    line_number = content[: match.start()].count("\n") + 1
                    matched_text = match.group(0)
                    snippet = (
                        lines[line_number - 1].strip()
                        if line_number <= len(lines)
                        else ""
                    )

                    line_start = content.rfind("\n", 0, match.start()) + 1
                    start_column = match.start() - line_start
                    end_column = match.end() - line_start

                    error_msg = (
                        f"Credential exfiltration blocked: {description} "
                        f"(line {line_number})"
                    )
                    self.findings.append(
                        {
                            "category": category,
                            "pattern": description,
                            "matched_text": matched_text,
                            "matched_pattern": compiled_re.pattern,
                            "line_number": line_number,
                            "start_column": start_column,
                            "end_column": end_column,
                            "snippet": snippet,
                            "label": label,
                            "error_message": error_msg,
                        }
                    )

        if not self.findings:
            return False, None, None

        first = self.findings[0]
        self.last_matched_pattern = first["pattern"]
        self.last_matched_text = first["matched_text"]
        self.last_category = first["category"]
        self.last_line_number = first["line_number"]
        self.last_start_column = first["start_column"]
        self.last_end_column = first["end_column"]

        details = {
            k: v
            for k, v in first.items()
            if k not in ("error_message", "matched_pattern")
        }
        details["total_findings"] = len(self.findings)

        if self.action == "block":
            return True, first["error_message"], details
        elif self.action == "log-only":
            return False, None, details
        else:
            return (
                False,
                "Credential exfiltration detected (warn mode) - execution allowed",
                details,
            )


def check_exfil_threats(
    command: str,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """Convenience function for checking bash commands for exfil patterns."""
    scanner = ExfilDetectionScanner(config)
    return scanner.check_command(command)
