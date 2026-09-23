"""
Audit logging for secret scanning operations.

Logs which engine was used, scan results, timing, and failures
for compliance and debugging purposes. Writes JSONL to state dir.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ai_guardian.config.utils import get_state_dir
from ai_guardian.scanners.strategies import ScanResult
from ai_guardian.violations.decision import PolicyDecision, safe_policy_decision

logger = logging.getLogger(__name__)


class ScanAuditLogger:
    """Log scan operations for audit trail."""

    def __init__(
        self,
        log_path: Optional[Path] = None,
        enabled: bool = True,
    ):
        self.enabled = enabled
        if log_path is None:
            log_path = get_state_dir() / "scan-audit.jsonl"
        self.log_path = log_path
        if self.enabled:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_scan(
        self,
        result: ScanResult,
        filename: str,
        strategy: str = "first-match",
        context: Optional[Dict] = None,
        policy_decision: Optional[PolicyDecision] = None,
    ) -> None:
        if not self.enabled:
            return

        entry: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": "scan_completed",
            "engine": result.engine,
            "strategy": strategy,
            "filename": filename,
            "has_secrets": result.has_secrets,
            "findings_count": len(result.secrets),
            "scan_time_ms": result.scan_time_ms,
            "error": result.error,
        }
        if context:
            entry["context"] = context
        if policy_decision is None:
            context = context or {}
            policy_decision = PolicyDecision(
                event="scan_completed",
                decision="block" if result.has_secrets else "allow",
                reason=("secret detected" if result.has_secrets else "no violation"),
                severity="high" if result.has_secrets else "none",
                confidence=(
                    max((match.confidence for match in result.secrets), default=0.0)
                    if result.has_secrets
                    else None
                ),
                source=result.engine or "secret_scanner",
                agent=context.get("agent", context.get("ide_type", "unknown")),
                repository=context.get("repository", context.get("project_path")),
                correlation_id=context.get(
                    "correlation_id",
                    context.get("run_id", context.get("session_id")),
                ),
                latency_ms=result.scan_time_ms,
            )
        entry["policy_decision"] = safe_policy_decision(policy_decision)

        self._write_entry(entry)

    def log_engine_failure(
        self,
        engine_type: str,
        error: str,
        filename: str,
        policy_decision: Optional[PolicyDecision] = None,
    ) -> None:
        if not self.enabled:
            return

        entry: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": "engine_failure",
            "engine": engine_type,
            "error": error,
            "filename": filename,
        }
        if policy_decision is None:
            policy_decision = PolicyDecision(
                event="scan_failed",
                decision="error",
                reason="scanner engine failure",
                severity="warning",
                source=engine_type or "secret_scanner",
            )
        entry["policy_decision"] = safe_policy_decision(policy_decision)
        self._write_entry(entry)

    def _write_entry(self, entry: Dict) -> None:
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.warning(f"Failed to write audit log: {e}")

    def get_recent_entries(
        self,
        limit: int = 100,
        engine_filter: Optional[str] = None,
    ) -> List[Dict]:
        entries: List[Dict] = []
        if not self.log_path.exists():
            return entries
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if engine_filter and entry.get("engine") != engine_filter:
                            continue
                        entries.append(entry)
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass  # intentionally silent — best-effort operation
        return entries[-limit:]
