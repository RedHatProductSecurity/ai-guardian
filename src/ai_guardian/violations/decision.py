"""Versioned, safe policy decision records.

The decision record is the common audit shape shared by hooks, scanners, the
SDK, MCP checks, REST responses, and external inspectors.  It deliberately
contains policy metadata only.  Raw commands, matched text, snippets, and
scanner-specific payloads stay in their existing compatibility fields and are
never copied into this record.
"""

from __future__ import annotations

import os
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

POLICY_DECISION_SCHEMA_VERSION = "1.0"
LEGACY_POLICY_DECISION_SCHEMA_VERSION = "0.0"

_DECISION_ALIASES = {
    "allow": "allow",
    "allowed": "allow",
    "approve": "allow",
    "approved": "allow",
    "block": "block",
    "blocked": "block",
    "deny": "block",
    "denied": "block",
    "warn": "warn",
    "warning": "warn",
    "log": "log",
    "log-only": "log",
    "redact": "redact",
    "error": "error",
}

_REASON_LABELS = {
    "secret_detected": "secret detected",
    "pii_detected": "PII detected",
    "directory_blocking": "directory access blocked",
    "tool_permission": "tool permission denied",
    "prompt_injection": "prompt injection detected",
    "jailbreak_detected": "jailbreak attempt detected",
    "ssrf_blocked": "SSRF protection triggered",
    "config_file_exfil": "config file exfiltration detected",
    "secret_redaction": "secret redacted",
    "secret_in_transcript": "secret detected in transcript",
    "pii_in_transcript": "PII detected in transcript",
    "prompt_injection_in_transcript": "prompt injection detected in transcript",
    "image_secret_detected": "secret detected in image",
    "image_pii_detected": "PII detected in image",
    "context_poisoning": "context poisoning detected",
    "supply_chain": "supply chain threat detected",
    "code_security": "code security issue detected",
    "offensive_language": "offensive language detected",
    "canary_detected": "canary token detected",
    "exfil_detection": "exfiltration pattern detected",
    "bash_exfil": "credential exfiltration detected",
}

_SENSITIVE_REASON_MARKERS = (
    "bearer ",
    "command=",
    "credential",
    "password",
    "pii",
    "password=",
    "secret",
    "secret=",
    "token=",
    "api_key=",
    "apikey=",
    "curl ",
    "wget ",
    " | ",
    "\n",
    "\r",
    "http://",
    "https://",
)


def _string_value(value: Any, default: str = "") -> str:
    """Convert enums and other scalar values to a bounded string."""
    if value is None:
        return default
    value = getattr(value, "value", value)
    return str(value)


def _safe_text(value: Any, default: str = "", max_length: int = 256) -> str:
    text = " ".join(_string_value(value, default).split())
    if not text:
        return default
    if len(text) > max_length:
        return text[: max_length - 3] + "..."
    return text


def _safe_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return max(0.0, min(1.0, number))


def _latency_value(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return max(0.0, number)


def _iso_timestamp(value: Any = None) -> str:
    if value:
        text = _safe_text(value, max_length=64)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is not None and "T" in text.upper():
                return text
        except ValueError:
            pass
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def default_policy_version() -> str:
    """Return a stable policy version without reading sensitive config data."""
    configured = os.environ.get("AI_GUARDIAN_POLICY_VERSION")
    if configured:
        return _safe_text(configured, default="unknown", max_length=128)
    try:
        from ai_guardian import __version__

        return f"ai-guardian/{__version__}"
    except (ImportError, AttributeError):
        return "ai-guardian/unknown"


def normalize_decision(action: Any, default: str = "allow") -> str:
    """Normalize legacy action names into the decision vocabulary."""
    value = _string_value(action).strip().lower()
    if value.startswith("ask"):
        # An unresolved ask is fail-closed in the policy pipeline.
        return "block"
    return _DECISION_ALIASES.get(value, default)


def _safe_reason(
    reason: Any,
    violation_type: Any = None,
    matched_text: Any = None,
) -> str:
    """Keep a useful policy summary while excluding likely raw content."""
    vtype = _string_value(violation_type).lower()
    fallback = _REASON_LABELS.get(vtype) or (
        f"{vtype} detected" if vtype else "policy evaluation completed"
    )
    if vtype in _REASON_LABELS:
        return fallback
    text = _safe_text(reason, default="", max_length=192)
    matched = _string_value(matched_text)
    lowered = text.lower()
    if not text or (matched and matched in text):
        return fallback
    if any(marker in lowered for marker in _SENSITIVE_REASON_MARKERS):
        return fallback
    return text


def _context_value(context: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = context.get(key)
        if value not in (None, ""):
            return value
    return None


@dataclass(frozen=True)
class PolicyDecision:
    """Safe, versioned policy decision and audit metadata.

    The fields intentionally exclude raw input.  ``to_dict`` only emits this
    allowlisted schema, even when a record is built from a legacy violation
    entry containing commands, snippets, or matched values.
    """

    event: str = "security_check"
    decision: str = "allow"
    reason: str = "policy evaluation completed"
    severity: Optional[str] = "none"
    confidence: Optional[float] = None
    policy_version: str = ""
    source: str = "unknown"
    agent: str = "unknown"
    repository: Optional[str] = None
    correlation_id: Optional[str] = None
    latency_ms: Optional[float] = None
    timestamp: str = ""
    schema_version: str = POLICY_DECISION_SCHEMA_VERSION
    violation_id: Optional[str] = None
    violation_type: Optional[str] = None
    rule_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.policy_version:
            object.__setattr__(self, "policy_version", default_policy_version())
        if not self.timestamp:
            object.__setattr__(self, "timestamp", _iso_timestamp())

    def to_dict(self) -> Dict[str, Any]:
        """Serialize only safe, schema-defined policy metadata."""
        result: Dict[str, Any] = {
            "schema_version": _safe_text(
                self.schema_version, POLICY_DECISION_SCHEMA_VERSION, 32
            ),
            "timestamp": _iso_timestamp(self.timestamp),
            "event": _safe_text(self.event, "security_check", 128),
            "decision": normalize_decision(self.decision, default="error"),
            "reason": _safe_reason(self.reason, self.violation_type),
            "severity": (
                _safe_text(self.severity, "none", 32) if self.severity else None
            ),
            "confidence": _safe_float(self.confidence),
            "policy_version": _safe_text(
                self.policy_version, default_policy_version(), 128
            ),
            "source": _safe_text(self.source, "unknown", 128),
            "agent": _safe_text(self.agent, "unknown", 128),
            "repository": (
                _safe_text(self.repository, max_length=512) if self.repository else None
            ),
            "correlation_id": (
                _safe_text(self.correlation_id, max_length=256)
                if self.correlation_id
                else None
            ),
            "latency_ms": _latency_value(self.latency_ms),
        }
        for key, value in (
            ("violation_id", self.violation_id),
            ("violation_type", self.violation_type),
            ("rule_id", self.rule_id),
        ):
            if value not in (None, ""):
                result[key] = _safe_text(value, max_length=256)
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PolicyDecision":
        """Read current or legacy records without exposing unknown fields."""
        return cls(
            event=_string_value(value.get("event"), "security_check"),
            decision=normalize_decision(value.get("decision"), default="error"),
            reason=_string_value(value.get("reason"), "policy evaluation completed"),
            severity=value.get("severity"),
            confidence=value.get("confidence"),
            policy_version=_string_value(
                value.get("policy_version"), default_policy_version()
            ),
            source=_string_value(value.get("source"), "unknown"),
            agent=_string_value(value.get("agent"), "unknown"),
            repository=value.get("repository"),
            correlation_id=value.get("correlation_id"),
            latency_ms=value.get("latency_ms"),
            timestamp=_string_value(value.get("timestamp")),
            schema_version=_string_value(
                value.get("schema_version"), LEGACY_POLICY_DECISION_SCHEMA_VERSION
            ),
            violation_id=value.get("violation_id"),
            violation_type=value.get("violation_type"),
            rule_id=value.get("rule_id"),
        )

    @classmethod
    def from_scan_result(
        cls,
        result: Any,
        context: Optional[Mapping[str, Any]] = None,
        *,
        source: str = "",
        event: Optional[str] = None,
        decision_override: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> "PolicyDecision":
        """Build a safe decision from the normalized scanner result."""
        ctx = context or {}
        violation_type = _string_value(getattr(result, "violation_type", ""))
        detected = bool(getattr(result, "detected", False))
        extra = getattr(result, "extra", {}) or {}
        action = extra.get("action") if isinstance(extra, Mapping) else None
        default = "warn" if detected else "allow"
        decision = normalize_decision(
            decision_override or action,
            default=("block" if getattr(result, "should_block", False) else default),
        )
        if decision_override:
            decision = normalize_decision(decision_override, default=default)
        confidence = getattr(result, "confidence", None)
        if confidence in (0, 0.0):
            confidence = None
        latency = getattr(result, "scan_time_ms", None)
        if not latency:
            latency = _context_value(ctx, "latency_ms")

        return cls(
            event=_string_value(
                event or _context_value(ctx, "hook_event", "event") or "scan"
            ),
            decision=decision,
            reason=_safe_reason(
                getattr(result, "error_message", ""),
                violation_type,
                getattr(result, "matched_text", ""),
            ),
            severity=getattr(result, "severity", None) or "none",
            confidence=confidence,
            policy_version=_string_value(
                _context_value(ctx, "policy_version") or default_policy_version()
            ),
            source=(
                source
                or _string_value(_context_value(ctx, "source"))
                or _string_value(getattr(result, "engine", ""))
                or _string_value(getattr(result, "config_section", ""))
                or "scanner"
            ),
            agent=_string_value(
                _context_value(ctx, "agent", "agent_type", "ide_type") or "unknown"
            ),
            repository=_context_value(ctx, "repository", "project_path"),
            correlation_id=_context_value(
                ctx, "correlation_id", "run_id", "session_id", "tool_use_id"
            ),
            latency_ms=latency,
            timestamp=timestamp or "",
            violation_id=getattr(result, "id", None),
            violation_type=violation_type or None,
            rule_id=getattr(result, "rule_id", None) or None,
        )

    @classmethod
    def from_violation(
        cls,
        violation_type: Any,
        blocked: Optional[Mapping[str, Any]] = None,
        context: Optional[Mapping[str, Any]] = None,
        *,
        severity: Optional[str] = None,
        source: str = "",
        violation_id: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> "PolicyDecision":
        """Build a safe decision from an existing legacy violation entry."""
        blocked_data = blocked or {}
        ctx = context or {}
        vtype = _string_value(violation_type)
        action = _context_value(blocked_data, "action") or _context_value(ctx, "action")
        default_decision = "block" if blocked_data else "allow"
        decision = normalize_decision(action, default=default_decision)
        return cls(
            event=_string_value(
                _context_value(ctx, "hook_event", "event") or "violation"
            ),
            decision=decision,
            reason=_safe_reason(
                _context_value(blocked_data, "reason", "message"),
                vtype,
                _context_value(blocked_data, "matched_text", "command"),
            ),
            severity=severity or "unknown",
            confidence=blocked_data.get("confidence"),
            policy_version=_string_value(
                _context_value(ctx, "policy_version") or default_policy_version()
            ),
            source=(
                source
                or _string_value(_context_value(ctx, "source"))
                or _string_value(_context_value(blocked_data, "source"))
                or "policy"
            ),
            agent=_string_value(
                _context_value(ctx, "agent", "agent_type", "ide_type") or "unknown"
            ),
            repository=_context_value(ctx, "repository", "project_path"),
            correlation_id=_context_value(
                ctx, "correlation_id", "run_id", "session_id", "tool_use_id"
            ),
            latency_ms=_context_value(ctx, "latency_ms"),
            timestamp=timestamp or "",
            violation_id=violation_id,
            violation_type=vtype or None,
            rule_id=_context_value(blocked_data, "rule_id"),
        )


def safe_policy_decision(value: Any) -> Optional[Dict[str, Any]]:
    """Return a schema-limited decision dictionary for output adapters."""
    if value is None:
        return None
    if isinstance(value, PolicyDecision):
        return value.to_dict()
    if isinstance(value, Mapping):
        return PolicyDecision.from_dict(value).to_dict()
    return None
