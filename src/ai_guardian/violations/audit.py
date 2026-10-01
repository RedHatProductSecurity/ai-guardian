"""Compliance audit logging for hook decisions.

The violation log remains the compatibility record for detected findings.  This
module provides the separate, opt-in audit trail for every final hook decision.
Only normalized tool metadata and the safe ``PolicyDecision`` record are
persisted; raw hook payloads and tool output are never written.
"""

import csv
import json
import logging
import os
import sys
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Iterator,
    List,
    Mapping,
    Optional,
    Sequence,
    cast,
)

try:
    import fcntl

    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

from ai_guardian.config.utils import get_state_dir, is_feature_enabled
from ai_guardian.violations.decision import (
    PolicyDecision,
    normalize_decision,
    safe_policy_decision,
)

logger = logging.getLogger(__name__)

AUDIT_LOG_SCHEMA_VERSION = "1.0"

DEFAULT_AUDIT_CONFIG: Dict[str, Any] = {
    "enabled": False,
    "log_all_tool_calls": True,
    "include_context": {
        "user_id": True,
        "session_id": True,
        "timestamp": True,
        "tool_parameters": True,
        "decision_reason": True,
        "hook_type": True,
    },
    "compliance_mode": {
        "soc2": False,
        "gdpr": False,
        "hipaa": False,
    },
    "retention_days": 90,
    "max_entries": 10000,
    "export_format": "json",
    "sensitive_data_masking": True,
    "output_file": None,
}

_DEFAULT_INCLUDE_CONTEXT: Mapping[str, Any] = DEFAULT_AUDIT_CONFIG["include_context"]
_WRITE_LOCK = threading.RLock()
_MAX_STRING_LENGTH = 4096
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "cookie",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)


@contextmanager
def _audit_process_lock(log_path: Path) -> Iterator[None]:
    """Serialize writes and rotation across hook processes."""
    lock_path = log_path.with_name(log_path.name + ".lock")
    lock_fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    fcntl_locked = False
    windows_locked = False
    try:
        os.chmod(lock_path, 0o600)
        if _HAS_FCNTL:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            fcntl_locked = True
        elif sys.platform == "win32":
            import msvcrt

            if os.fstat(lock_fd).st_size == 0:
                os.write(lock_fd, b"\0")
            os.lseek(lock_fd, 0, os.SEEK_SET)
            locking = cast(Callable[[int, int, int], None], getattr(msvcrt, "locking"))
            locking(lock_fd, int(getattr(msvcrt, "LK_LOCK")), 1)
            windows_locked = True
        else:
            logger.warning("Audit log process locking is unavailable on this platform")
        yield
    finally:
        if fcntl_locked:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        elif windows_locked:
            import msvcrt

            os.lseek(lock_fd, 0, os.SEEK_SET)
            locking = cast(Callable[[int, int, int], None], getattr(msvcrt, "locking"))
            locking(lock_fd, int(getattr(msvcrt, "LK_UNLCK")), 1)
        os.close(lock_fd)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    value = getattr(value, "value", value)
    return str(value)


def _event_name(value: Any) -> str:
    display_name = getattr(value, "display_name", None)
    if display_name:
        return str(display_name)
    return _text(value, "unknown")


def _context_value(context: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = context.get(key)
        if value not in (None, ""):
            return value
    return None


def _merge_config(config: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Merge a section or complete config with safe audit defaults."""
    merged: Dict[str, Any] = {
        key: (dict(value) if isinstance(value, dict) else value)
        for key, value in DEFAULT_AUDIT_CONFIG.items()
    }

    if not isinstance(config, Mapping):
        return merged

    section = config.get("audit_logging")
    if not isinstance(section, Mapping):
        section = config

    for key, value in section.items():
        if key in ("include_context", "compliance_mode") and isinstance(value, Mapping):
            merged[key].update(value)
        elif key in merged:
            merged[key] = value
    return merged


def _json_safe(value: Any) -> Any:
    """Convert arbitrary hook metadata to JSON-compatible scalar values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return _text(value)


def _is_sensitive_key(key: Any) -> bool:
    normalized = _text(key).lower().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _sanitize_text(value: str) -> str:
    """Redact configured-independent secrets and PII from one string."""
    try:
        from ai_guardian.scanners.sanitizer import sanitize_text

        result = sanitize_text(value, no_threats=True)
        return result.get("sanitized_text", value)
    except Exception as error:
        logger.warning("Audit metadata masking failed: %s", error)
        return value


def _sanitize_value(
    value: Any,
    path: str,
    masked_fields: List[str],
    masking_enabled: bool,
) -> Any:
    """Recursively sanitize metadata while preserving its useful shape."""
    if not masking_enabled:
        return _json_safe(value)

    if isinstance(value, Mapping):
        sanitized: Dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            item_path = f"{path}.{key_text}" if path else key_text
            if _is_sensitive_key(key_text) and item not in (None, "", [], {}):
                sanitized[key_text] = "[MASKED]"
                masked_fields.append(item_path)
                continue
            sanitized[key_text] = _sanitize_value(
                item, item_path, masked_fields, masking_enabled
            )
        return sanitized

    if isinstance(value, (list, tuple, set)):
        return [
            _sanitize_value(item, f"{path}[{index}]", masked_fields, masking_enabled)
            for index, item in enumerate(value)
        ]

    if isinstance(value, str):
        original = value
        if len(value) > _MAX_STRING_LENGTH:
            value = value[:_MAX_STRING_LENGTH] + "...[TRUNCATED]"
            masked_fields.append(path)
        value = _sanitize_text(value)
        if value != original and path not in masked_fields:
            masked_fields.append(path)
        return value

    return _json_safe(value)


def _parse_timestamp(value: Any) -> datetime:
    if not value:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    try:
        text = _text(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (TypeError, ValueError):
        return datetime.fromtimestamp(0, tz=timezone.utc)


def _split_violation_types(value: Any) -> List[str]:
    if value in (None, ""):
        return []
    return [part.strip() for part in _text(value).split(",") if part.strip()]


class AuditLogger:
    """Write sanitized, final policy decisions to a compliance JSONL log."""

    def __init__(
        self,
        log_path: Optional[Path] = None,
        config: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.config = _merge_config(
            config if config is not None else self._load_config()
        )
        self.enabled = is_feature_enabled(self.config.get("enabled"), default=False)

        configured_path = self.config.get("output_file")
        if log_path is None and isinstance(configured_path, str) and configured_path:
            log_path = Path(configured_path).expanduser()
        if log_path is None:
            log_path = get_state_dir() / "audit.jsonl"
        self.log_path = Path(log_path).expanduser()

        if self.enabled:
            self.log_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                self.log_path.parent.chmod(0o700)
                if self.log_path.exists():
                    self.log_path.chmod(0o600)
            except OSError as error:
                logger.warning(
                    "Unable to harden audit log permissions for %s: %s",
                    self.log_path,
                    error,
                )

    @staticmethod
    def _load_config() -> Optional[Dict[str, Any]]:
        try:
            from ai_guardian.config.loaders import _load_config_section

            section, error = _load_config_section("audit_logging")
            if error:
                logger.warning("Audit logging config error: %s", error)
            return section
        except Exception as error:
            logger.warning("Unable to load audit logging config: %s", error)
            return None

    def _should_log(self, decision: str) -> bool:
        if not self.enabled:
            return False
        return bool(self.config.get("log_all_tool_calls", True)) or decision != "allow"

    def _compliance_flags(self) -> Dict[str, bool]:
        mode = self.config.get("compliance_mode") or {}
        return {
            "soc2_logged": bool(mode.get("soc2", False)),
            "gdpr_processing_activity": bool(mode.get("gdpr", False)),
            "hipaa_access_log": bool(mode.get("hipaa", False)),
        }

    def log_decision(
        self,
        hook_type: Any,
        decision: Any,
        context: Optional[Mapping[str, Any]] = None,
        *,
        event_type: Optional[str] = None,
        user_id: Any = None,
        session_id: Any = None,
        tool_name: Any = None,
        tool_parameters: Any = None,
        decision_reason: Optional[str] = None,
        policy_matched: Any = None,
        severity: Optional[str] = None,
        violation_type: Any = None,
        policy_decision: Optional[Any] = None,
        timestamp: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Log one normalized decision and return the persisted entry.

        ``context`` is an input convenience only.  It is allowlisted into the
        entry and is never persisted wholesale.
        """
        normalized_decision = normalize_decision(decision, default="error")
        if not self._should_log(normalized_decision):
            return None

        context = context or {}
        hook_name = _event_name(hook_type)
        timestamp = timestamp or _timestamp()
        user_id = (
            user_id
            if user_id is not None
            else _context_value(context, "user_id", "userId")
        )
        session_id = (
            session_id
            if session_id is not None
            else _context_value(context, "session_id", "sessionId")
        )
        tool_name = (
            tool_name
            if tool_name is not None
            else _context_value(context, "tool_name", "toolName")
        )
        if tool_parameters is None:
            tool_parameters = _context_value(
                context, "tool_parameters", "parameters", "tool_input"
            )
        violation_type = (
            violation_type
            if violation_type is not None
            else _context_value(context, "violation_type")
        )
        policy_matched = (
            policy_matched
            if policy_matched is not None
            else _context_value(context, "policy_matched", "rule_id")
        )

        if decision_reason is None:
            if normalized_decision == "allow":
                decision_reason = "No policy violations"
            elif normalized_decision == "redact":
                decision_reason = "Sensitive data redacted"
            elif normalized_decision == "warn":
                decision_reason = "Policy warning; operation allowed"
            elif normalized_decision == "log":
                decision_reason = "Policy event logged; operation allowed"
            elif normalized_decision == "error":
                decision_reason = "Policy evaluation failed"
            else:
                decision_reason = "Policy blocked operation"

        if severity is None:
            severity = {
                "allow": "none",
                "redact": "warning",
                "warn": "warning",
                "log": "info",
                "block": "high",
                "error": "warning",
            }.get(normalized_decision, "none")

        agent = _context_value(context, "agent", "agent_type", "ide_type") or "unknown"
        repository = _context_value(context, "repository", "project_path")
        correlation_id = _context_value(
            context, "correlation_id", "run_id", "session_id", "tool_use_id"
        )
        latency_ms = _context_value(context, "latency_ms")

        if policy_decision is None:
            policy_decision = PolicyDecision(
                event=hook_name,
                decision=normalized_decision,
                reason=decision_reason,
                severity=severity,
                policy_version=_text(
                    _context_value(context, "policy_version"), default=""
                ),
                source=_text(_context_value(context, "source"), default="hook"),
                agent=_text(agent, default="unknown"),
                repository=repository,
                correlation_id=correlation_id,
                latency_ms=latency_ms,
                timestamp=timestamp,
                violation_type=_text(violation_type) or None,
                rule_id=_text(policy_matched) or None,
            )
        canonical_decision = safe_policy_decision(policy_decision)

        masked_fields: List[str] = []
        masking_enabled = bool(self.config.get("sensitive_data_masking", True))
        configured_context = self.config.get("include_context")
        if isinstance(configured_context, Mapping):
            include_context: Mapping[str, Any] = configured_context
        else:
            include_context = _DEFAULT_INCLUDE_CONTEXT
        sanitized_parameters = _sanitize_value(
            tool_parameters,
            "tool_parameters",
            masked_fields,
            masking_enabled,
        )
        sanitized_user_id = _sanitize_value(
            user_id, "user_id", masked_fields, masking_enabled
        )
        sanitized_reason = _sanitize_value(
            _text(decision_reason),
            "decision_reason",
            masked_fields,
            masking_enabled,
        )
        sanitized_policy_matched = _sanitize_value(
            policy_matched,
            "policy_matched",
            masked_fields,
            masking_enabled,
        )

        event_name = event_type or (
            "violation"
            if normalized_decision in ("block", "error")
            else "tool_call" if tool_name else "hook_decision"
        )
        entry: Dict[str, Any] = {
            "schema_version": AUDIT_LOG_SCHEMA_VERSION,
            "event_type": event_name,
            "decision": normalized_decision,
            "tool_name": _json_safe(tool_name),
            "policy_matched": sanitized_policy_matched,
            "compliance_flags": self._compliance_flags(),
            "masked_fields": masked_fields,
            "policy_decision": canonical_decision,
        }

        if include_context.get("timestamp", True):
            entry["timestamp"] = timestamp
        if include_context.get("hook_type", True):
            entry["hook_type"] = hook_name
        if include_context.get("user_id", True):
            entry["user_id"] = sanitized_user_id
        if include_context.get("session_id", True):
            entry["session_id"] = _json_safe(session_id)
        if include_context.get("tool_parameters", True):
            entry["tool_parameters"] = sanitized_parameters
        if include_context.get("decision_reason", True):
            entry["decision_reason"] = sanitized_reason

        try:
            with _WRITE_LOCK, _audit_process_lock(self.log_path):
                self._append_entry(entry)
                self._rotate_log_if_needed()
        except Exception as error:
            logger.warning("Failed to write audit log %s: %s", self.log_path, error)
            return None
        return entry

    def _append_entry(self, entry: Mapping[str, Any]) -> None:
        """Append one entry using private file permissions."""
        file_descriptor = os.open(
            str(self.log_path),
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o600,
        )
        try:
            os.chmod(self.log_path, 0o600)
            with os.fdopen(file_descriptor, "a", encoding="utf-8") as stream:
                file_descriptor = -1
                stream.write(json.dumps(entry, sort_keys=True) + "\n")
        finally:
            if file_descriptor >= 0:
                os.close(file_descriptor)

    def log_hook_decision(
        self,
        hook_data: Mapping[str, Any],
        result: Mapping[str, Any],
        *,
        adapter: Any = None,
        normalized: Any = None,
    ) -> Optional[Dict[str, Any]]:
        """Log the final decision returned by the hook pipeline."""
        if not isinstance(hook_data, Mapping) or not isinstance(result, Mapping):
            return None

        try:
            if adapter is None or normalized is None:
                from ai_guardian.hook_adapters import detect_adapter

                adapter = adapter or detect_adapter(dict(hook_data))
                normalized = normalized or adapter.normalize_input(dict(hook_data))

            hook_event = normalized.event
            tool_name = normalized.tool_name
            violation_type = result.get("_violation_type")
            decision = self._decision_from_result(result, violation_type)
            context = {
                "user_id": _context_value(hook_data, "user_id", "userId"),
                "session_id": normalized.session_id
                or _context_value(hook_data, "session_id", "sessionId"),
                "tool_use_id": normalized.tool_use_id
                or _context_value(hook_data, "tool_use_id", "toolUseId"),
                "tool_name": tool_name,
                "tool_parameters": normalized.tool_input if tool_name else None,
                "agent": getattr(adapter, "agent_type", "unknown"),
                "ide_type": getattr(adapter, "name", "unknown"),
                "repository": normalized.working_dir
                or _context_value(hook_data, "cwd", "working_dir"),
                "correlation_id": _context_value(
                    hook_data, "run_id", "_ai_guardian_run_id"
                ),
                "source": "hook",
                "violation_type": violation_type,
            }
            return self.log_decision(
                hook_event,
                decision,
                context,
                tool_name=tool_name,
                tool_parameters=context["tool_parameters"],
                violation_type=violation_type,
                policy_matched=violation_type,
            )
        except Exception as error:
            logger.warning("Failed to build hook audit record: %s", error)
            return None

    @staticmethod
    def _decision_from_result(result: Mapping[str, Any], violation_type: Any) -> str:
        explicit = result.get("_audit_decision") or result.get("decision")
        if explicit:
            return normalize_decision(explicit, default="error")
        if result.get("_blocked"):
            return "block"
        types = _split_violation_types(violation_type)
        if "secret_redaction" in types or "pii_redaction" in types:
            return "redact"
        if result.get("_log_only"):
            return "log"
        if result.get("_warning"):
            return "warn"
        return "allow"

    def get_recent_entries(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Read recent valid entries in chronological order."""
        if not self.log_path.exists():
            return []
        entries: List[Dict[str, Any]] = []
        try:
            with open(self.log_path, "r", encoding="utf-8") as stream:
                for line in stream:
                    try:
                        value = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("Skipping invalid audit JSONL entry")
                        continue
                    if isinstance(value, dict):
                        entries.append(value)
        except OSError as error:
            logger.error("Unable to read audit log %s: %s", self.log_path, error)
            return []
        return entries[-limit:] if limit > 0 else entries

    def export(
        self,
        export_path: Optional[Path] = None,
        export_format: Optional[str] = None,
    ) -> bool:
        """Export the audit trail as JSON or CSV."""
        format_name = (
            export_format or self.config.get("export_format") or "json"
        ).lower()
        if format_name not in ("json", "csv"):
            logger.warning("Unknown audit export format '%s'; using JSON", format_name)
            format_name = "json"
        if export_path is None:
            export_path = self.get_export_path(format_name)
        export_path = Path(export_path).expanduser()

        entries = self.get_recent_entries(limit=0)
        try:
            export_path.parent.mkdir(parents=True, exist_ok=True)
            if format_name == "csv":
                self._export_csv(export_path, entries)
            else:
                with open(export_path, "w", encoding="utf-8") as stream:
                    json.dump(entries, stream, indent=2, sort_keys=True)
                    stream.write("\n")
            return True
        except (OSError, TypeError, ValueError) as error:
            logger.error("Unable to export audit log to %s: %s", export_path, error)
            return False

    def get_export_path(self, export_format: Optional[str] = None) -> Path:
        """Return a default export path that cannot overwrite the JSONL source."""
        format_name = (
            export_format or self.config.get("export_format") or "json"
        ).lower()
        if format_name not in ("json", "csv"):
            format_name = "json"
        export_path = self.log_path.with_suffix("." + format_name)
        if export_path == self.log_path:
            export_path = self.log_path.with_name(
                f"{self.log_path.name}.export.{format_name}"
            )
        return export_path

    def export_audit(
        self,
        export_path: Optional[Path] = None,
        export_format: Optional[str] = None,
    ) -> bool:
        """Compatibility alias for callers that use an explicit audit name."""
        return self.export(export_path=export_path, export_format=export_format)

    @staticmethod
    def _export_csv(export_path: Path, entries: Sequence[Mapping[str, Any]]) -> None:
        fields = [
            "timestamp",
            "event_type",
            "hook_type",
            "user_id",
            "session_id",
            "tool_name",
            "tool_parameters",
            "decision",
            "decision_reason",
            "policy_matched",
            "compliance_flags",
            "masked_fields",
            "policy_decision",
        ]
        with open(export_path, "w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for entry in entries:
                row = {}
                for field in fields:
                    value = entry.get(field, "")
                    if isinstance(value, (dict, list)):
                        value = json.dumps(value, sort_keys=True)
                    row[field] = value
                writer.writerow(row)

    def clear_log(self) -> bool:
        """Remove the audit log without changing its configuration."""
        try:
            if self.log_path.exists():
                with _WRITE_LOCK, _audit_process_lock(self.log_path):
                    if self.log_path.exists():
                        self.log_path.unlink()
            return True
        except OSError as error:
            logger.error("Unable to clear audit log %s: %s", self.log_path, error)
            return False

    def _rotate_log_if_needed(self) -> None:
        if not self.log_path.exists():
            return
        try:
            retention_days = max(1, int(self.config.get("retention_days", 90)))
            max_entries = max(1, int(self.config.get("max_entries", 10000)))
        except (TypeError, ValueError):
            logger.warning("Invalid audit retention configuration; using defaults")
            retention_days = 90
            max_entries = 10000

        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        entries = [
            entry
            for entry in self.get_recent_entries(limit=0)
            if _parse_timestamp(entry.get("timestamp")) >= cutoff
        ]
        entries = entries[-max_entries:]
        file_descriptor, temporary_path = tempfile.mkstemp(
            dir=str(self.log_path.parent),
            prefix=f".{self.log_path.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as stream:
                file_descriptor = -1
                for entry in entries:
                    stream.write(json.dumps(entry, sort_keys=True) + "\n")
            os.replace(temporary_path, self.log_path)
            os.chmod(self.log_path, 0o600)
        finally:
            if file_descriptor >= 0:
                os.close(file_descriptor)
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                # intentionally silent — atomic replace already removed the temp file
                pass
