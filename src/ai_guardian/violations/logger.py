#!/usr/bin/env python3
"""
Violation Logger Module

Logs blocked operations to a JSONL file for audit and review.
Supports violation types:
- tool_permission: Tool/skill blocked by policy
- directory_blocking: File in denied directory
- secret_detected: Gitleaks found secrets
- prompt_injection: Malicious prompt detected
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ai_guardian.config.utils import get_config_dir, get_state_dir, is_feature_enabled

logger = logging.getLogger(__name__)


class ViolationLogger:
    """Log blocked operations for audit and console review."""

    def __init__(self, log_path: Optional[Path] = None, config: Optional[Dict] = None):
        """
        Initialize violation logger.

        Args:
            log_path: Optional custom log file path
            config: Optional configuration dict
        """
        self.config = config or self._load_config()

        # Determine log path
        if log_path is None:
            state_dir = get_state_dir()
            log_path = state_dir / "violations.jsonl"

        self.log_path = log_path

        # Only create log directory if logging is enabled
        if self._is_logging_enabled():
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_violation(
        self,
        violation_type: str,
        blocked: Dict,
        context: Dict,
        suggestion: Optional[Dict] = None,
        severity: str = "warning",
        violation_id: Optional[str] = None,
    ):
        """
        Log a violation to JSONL file.

        Args:
            violation_type: Type of violation (tool_permission, directory_blocking, etc.)
            blocked: Details about what was blocked
            context: Context information (IDE type, project path, etc.)
            suggestion: Optional suggestion for resolving the violation
            severity: Severity level (warning, high, critical)
        """
        # Check if logging is enabled
        if not self._is_logging_enabled():
            logger.debug("Violation logging is disabled")
            return

        # Check if this violation type should be logged
        if not self._should_log_type(violation_type):
            logger.debug(
                f"Violation type {violation_type} is not configured to be logged"
            )
            return

        try:
            entry = {
                "id": violation_id,
                "timestamp": datetime.now(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "violation_type": violation_type,
                "severity": severity,
                "blocked": blocked,
                "context": context,
                "suggestion": suggestion or {},
                "resolved": False,
                "resolved_at": None,
                "resolved_action": None,
            }

            # Append to JSONL file
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")

            logger.debug(f"Logged {violation_type} violation to {self.log_path}")

            # Increment running counter (independent of log rotation)
            try:
                from ai_guardian.violations.counter import ViolationCounter

                ViolationCounter().increment(violation_type)
            except Exception as counter_err:
                logger.warning(f"Failed to increment violation counter: {counter_err}")

            # Rotate log if needed
            self._rotate_log_if_needed()

        except Exception as e:
            # Fail-open: don't block operations if logging fails
            logger.warning(f"Failed to log violation: {e}")

    def get_recent_violations(
        self,
        limit: int = 50,
        violation_type: Optional[str] = None,
        resolved: Optional[bool] = None,
        tool_use_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> List[Dict]:
        """
        Get recent violations from log.

        Args:
            limit: Maximum number of violations to return
            violation_type: Optional filter by violation type
            resolved: Optional filter by resolved status (True/False/None for all)
            tool_use_id: Optional filter by context.tool_use_id
            session_id: Optional filter by context.session_id

        Returns:
            list: List of violation entries (most recent first)
        """
        if not self.log_path.exists():
            return []

        violations = []
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line)

                        # Apply filters
                        if (
                            violation_type is not None
                            and entry.get("violation_type") != violation_type
                        ):
                            continue

                        if (
                            resolved is not None
                            and entry.get("resolved", False) != resolved
                        ):
                            continue

                        if (
                            tool_use_id is not None
                            and entry.get("context", {}).get("tool_use_id")
                            != tool_use_id
                        ):
                            continue

                        if (
                            session_id is not None
                            and entry.get("context", {}).get("session_id") != session_id
                        ):
                            continue

                        violations.append(entry)

                    except json.JSONDecodeError as e:
                        logger.warning(f"Skipping invalid JSON line: {e}")
                        continue

            # Return most recent first
            violations = violations[-limit:][::-1]
            return violations

        except Exception as e:
            logger.error(f"Error reading violations log: {e}")
            return []

    def mark_resolved(
        self, timestamp: str, action: str = "approved", note: Optional[str] = None
    ) -> bool:
        """
        Mark a violation as resolved.

        Args:
            timestamp: Timestamp of the violation to resolve
            action: Resolution action (approved, denied, etc.)
            note: Optional note about resolution

        Returns:
            bool: True if violation was found and marked resolved
        """
        if not self.log_path.exists():
            return False

        try:
            # Read all violations
            violations = []
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        violations.append(entry)
                    except json.JSONDecodeError:
                        continue

            # Find and update the violation
            found = False
            for entry in violations:
                if entry.get("timestamp") == timestamp:
                    entry["resolved"] = True
                    entry["resolved_at"] = (
                        datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                    )
                    entry["resolved_action"] = action
                    if note:
                        entry["resolved_note"] = note
                    found = True
                    break

            if not found:
                return False

            # Write back all violations
            with open(self.log_path, "w", encoding="utf-8") as f:
                for entry in violations:
                    f.write(json.dumps(entry) + "\n")

            return True

        except Exception as e:
            logger.error(f"Error marking violation as resolved: {e}")
            return False

    def mark_unresolved(self, timestamp: str) -> bool:
        """
        Mark a violation as unresolved (undo resolution).

        Args:
            timestamp: Timestamp of the violation to unresolve

        Returns:
            bool: True if violation was found and marked unresolved
        """
        if not self.log_path.exists():
            return False

        try:
            # Read all violations
            violations = []
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        violations.append(entry)
                    except json.JSONDecodeError:
                        continue

            # Find and update the violation
            found = False
            for entry in violations:
                if entry.get("timestamp") == timestamp:
                    # Remove resolved fields
                    entry["resolved"] = False
                    entry.pop("resolved_at", None)
                    entry.pop("resolved_action", None)
                    entry.pop("resolved_note", None)
                    found = True
                    break

            if not found:
                return False

            # Write back all violations
            with open(self.log_path, "w", encoding="utf-8") as f:
                for entry in violations:
                    f.write(json.dumps(entry) + "\n")

            return True

        except Exception as e:
            logger.error(f"Error marking violation as unresolved: {e}")
            return False

    def clear_log(self) -> bool:
        """
        Clear the violations log.

        Returns:
            bool: True if log was cleared successfully
        """
        try:
            if self.log_path.exists():
                self.log_path.unlink()
                logger.info(f"Cleared violations log at {self.log_path}")
            return True
        except Exception as e:
            logger.error(f"Error clearing violations log: {e}")
            return False

    def export_violations(
        self, export_path: Path, violation_type: Optional[str] = None
    ) -> bool:
        """
        Export violations to a JSON file.

        Args:
            export_path: Path to export file
            violation_type: Optional filter by violation type

        Returns:
            bool: True if export was successful
        """
        try:
            violations = self.get_recent_violations(
                limit=10000, violation_type=violation_type  # Export all violations
            )

            with open(export_path, "w", encoding="utf-8") as f:
                json.dump(violations, f, indent=2)

            logger.info(f"Exported {len(violations)} violations to {export_path}")
            return True

        except Exception as e:
            logger.error(f"Error exporting violations: {e}")
            return False

    def _load_config(self) -> Dict:
        """
        Load violation logging configuration from ai-guardian.json.

        Returns:
            dict: Configuration or defaults
        """
        try:
            config_dir = get_config_dir()
            config_path = config_dir / "ai-guardian.json"

            if not config_path.exists():
                # Try project local config
                config_path = Path.cwd() / ".ai-guardian.json"

            if not config_path.exists():
                return self._get_default_config()

            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

            return config.get("violation_logging", self._get_default_config())

        except Exception as e:
            logger.warning(f"Error loading violation logging config: {e}")
            return self._get_default_config()

    def _get_default_config(self) -> Dict:
        """Get default configuration."""
        return {
            "enabled": True,
            "max_entries": 1000,
            "retention_days": 30,
            "log_types": [
                "tool_permission",
                "directory_blocking",
                "secret_detected",
                "secret_redaction",
                "prompt_injection",
                "jailbreak_detected",
                "ssrf_blocked",
                "config_file_exfil",
                "pii_detected",
                "secret_in_transcript",
                "pii_in_transcript",
                "prompt_injection_in_transcript",
                "annotation_suppressed",
                "image_secret_detected",
                "image_pii_detected",
                "context_poisoning",
            ],
        }

    def _is_logging_enabled(self) -> bool:
        """Check if violation logging is enabled."""
        return is_feature_enabled(self.config.get("enabled"), default=True)

    def _should_log_type(self, violation_type: str) -> bool:
        """Check if a violation type should be logged.

        New violation types added after config creation are logged by
        default so existing users automatically get coverage for new
        detection capabilities.  When ``_known_log_types`` is present
        in the config, only types absent from that baseline are
        auto-enabled — this lets users explicitly remove types without
        them being re-enabled.
        """
        log_types = self.config.get("log_types", [])
        if not log_types:
            return True
        if violation_type in log_types:
            return True
        known = self.config.get("_known_log_types")
        if known is not None:
            return violation_type not in known
        default_types = self._get_default_config()["log_types"]
        if violation_type in default_types and violation_type not in log_types:
            return True
        return False

    def _rotate_log_if_needed(self):
        """Rotate log file if it exceeds max_entries or retention_days."""
        try:
            if not self.log_path.exists():
                return

            max_entries = self.config.get("max_entries", 1000)
            retention_days = self.config.get("retention_days", 30)

            # Read all violations
            violations = []
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        violations.append(entry)
                    except json.JSONDecodeError:
                        continue

            # Filter by retention days
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)
            violations = [
                v
                for v in violations
                if self._parse_timestamp(v.get("timestamp")) > cutoff_date
            ]

            # Limit by max_entries (keep most recent)
            if len(violations) > max_entries:
                violations = violations[-max_entries:]

            # Write back filtered violations
            with open(self.log_path, "w", encoding="utf-8") as f:
                for entry in violations:
                    f.write(json.dumps(entry) + "\n")

            logger.debug(f"Log rotation: kept {len(violations)} violations")

        except Exception as e:
            logger.warning(f"Error rotating log: {e}")

    def _parse_timestamp(self, timestamp_str: Optional[str]) -> datetime:
        """
        Parse ISO timestamp string to datetime.

        Args:
            timestamp_str: ISO format timestamp string

        Returns:
            datetime: Parsed datetime (timezone-aware) or epoch if parsing fails
        """
        if not timestamp_str:
            return datetime.fromtimestamp(0, tz=timezone.utc)

        try:
            # Remove 'Z' suffix and parse as UTC
            if timestamp_str.endswith("Z"):
                timestamp_str = timestamp_str[:-1] + "+00:00"
            dt = datetime.fromisoformat(timestamp_str)
            # Ensure timezone-aware
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, AttributeError):
            return datetime.fromtimestamp(0, tz=timezone.utc)
