"""
AI Guardian SDK — programmatic security checking for Python agent programs.

Provides opt-in protection for programs where IDE hooks don't apply
(LangChain, custom scripts, direct LLM API calls, etc.).

This SDK is additive — it cannot bypass or weaken existing hook-based
enforcement. Hooks remain the enforcement layer for IDE sessions.

Usage:
    from ai_guardian.sdk import monitor

    # Direct mode (default) — in-process, no daemon
    with monitor(action="block") as session:
        session.check_content(text)
        session.check_file("/path/to/file")
        session.check_command("curl http://example.com")

    # REST mode — delegates to daemon, auto-starts if needed
    with monitor(action="block", mode="rest") as session:
        session.check_content(text)

    # Config overlay — deep-merge on top of global + project config
    from ai_guardian import configure
    configure(overlay={"secret_scanning": {"enabled": True}})
    with monitor() as session:
        session.check_content(text)

    # Or via environment variables (CI/CD):
    #   AI_GUARDIAN_CONFIG_OVERLAY=/path/to/overlay.json
    #   AI_GUARDIAN_CONFIG_INLINE='{"preferred_ui":"headless"}'
"""

import logging
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class CheckResult:
    """Result of a security check."""

    blocked: bool = False
    detected: bool = False
    violation_type: Optional[str] = None
    message: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class SecurityViolation(Exception):
    """Raised when action='block' and a threat is detected."""

    def __init__(self, result: CheckResult):
        self.result = result
        super().__init__(result.message or "Security violation detected")


class _SecurityWarning(UserWarning):
    """Warning category for action='warn' detections."""

    pass


class GuardSession:
    """Base session with shared action-handling logic."""

    def __init__(self, action: str, config: Optional[Dict[str, Any]] = None):
        self._action = action
        self._config = config
        self._results: List[CheckResult] = []

    @property
    def results(self) -> List[CheckResult]:
        """All results collected during this session."""
        return list(self._results)

    def check_content(self, text: str, *, filename: str = "input") -> CheckResult:
        """Check text for secrets, prompt injection, context poisoning."""
        raise NotImplementedError

    def check_file(self, file_path: str, content: Optional[str] = None) -> CheckResult:
        """Check file path access and optionally scan file content."""
        raise NotImplementedError

    def check_command(self, command: str) -> CheckResult:
        """Check a bash command for threats."""
        raise NotImplementedError

    def sanitize(self, text: str) -> Dict[str, Any]:
        """Sanitize text, redacting secrets and PII."""
        raise NotImplementedError

    def get_violations(
        self,
        *,
        tool_use_id: Optional[str] = None,
        session_id: Optional[str] = None,
        violation_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Query hook-triggered violations with sanitized output.

        Returns violation records with secrets/PII redacted so results
        are safe to store in external databases.

        Args:
            tool_use_id: Filter by tool_use_id from hook context
            session_id: Filter by session_id from hook context
            violation_type: Filter by violation type
            limit: Maximum number of violations to return

        Returns:
            List of sanitized violation dicts with: violation_type, message,
            tool_name, tool_use_id, session_id, timestamp, severity
        """
        raise NotImplementedError

    def _handle_result(self, result: CheckResult) -> CheckResult:
        """Apply action policy to a result."""
        self._results.append(result)
        if result.blocked and self._action == "block":
            raise SecurityViolation(result)
        if result.detected and self._action == "warn":
            warnings.warn(
                result.message or "Security issue detected",
                _SecurityWarning,
                stacklevel=3,
            )
        return result

    @staticmethod
    def _sanitize_violation(v: Dict, sanitize_fn) -> Dict[str, Any]:
        """Extract and sanitize a single violation record."""
        blocked = v.get("blocked", {})
        if not isinstance(blocked, dict):
            blocked = {}
        ctx = v.get("context", {})
        if not isinstance(ctx, dict):
            ctx = {}

        raw_message = (
            v.get("message") or blocked.get("reason") or blocked.get("message") or ""
        )
        if raw_message:
            result = sanitize_fn(raw_message)
            safe_message = result.get("sanitized_text", raw_message)
        else:
            safe_message = ""

        return {
            "violation_type": v.get("violation_type", ""),
            "message": safe_message,
            "tool_name": ctx.get("tool_name", "") or blocked.get("tool", ""),
            "tool_use_id": ctx.get("tool_use_id", ""),
            "session_id": ctx.get("session_id", ""),
            "timestamp": v.get("timestamp", ""),
            "severity": v.get("severity", ""),
        }

    @staticmethod
    def _merge_results(results: List[CheckResult]) -> CheckResult:
        """Merge multiple check results into one."""
        if not results:
            return CheckResult()
        blocked = any(r.blocked for r in results)
        detected = any(r.detected for r in results)
        messages = [r.message for r in results if r.message]
        types = [r.violation_type for r in results if r.violation_type]
        return CheckResult(
            blocked=blocked,
            detected=detected,
            violation_type=(
                types[0] if len(types) == 1 else (",".join(types) if types else None)
            ),
            message="; ".join(messages) if messages else None,
            details=(
                {
                    "individual_results": [
                        {"violation_type": r.violation_type, "message": r.message}
                        for r in results
                        if r.detected
                    ]
                }
                if len(results) > 1 and detected
                else (results[0].details if results else None)
            ),
        )


class _DirectSession(GuardSession):
    """In-process detection — calls detection functions directly."""

    def __init__(self, action: str, config: Optional[Dict[str, Any]] = None):
        super().__init__(action, config)
        self._ensure_config()

    def _ensure_config(self):
        if self._config is None:
            from ai_guardian.config.loaders import _load_config_file

            cfg, _ = _load_config_file()
            self._config = cfg or {}

    def check_content(self, text: str, *, filename: str = "input") -> CheckResult:
        results = []

        secret_cfg = self._config.get("secret_scanning", {})
        if secret_cfg.get("enabled", True):
            try:
                from ai_guardian.scanners.secret_scanning import (
                    check_secrets_with_gitleaks,
                )

                has_secrets, msg = check_secrets_with_gitleaks(
                    text,
                    filename=filename,
                    secret_config=secret_cfg,
                )
                if has_secrets:
                    results.append(
                        CheckResult(
                            blocked=True,
                            detected=True,
                            violation_type="secret_detected",
                            message=msg,
                        )
                    )
            except Exception as e:
                logger.debug("Secret scanning unavailable: %s", e)

        pi_cfg = self._config.get("prompt_injection", {})
        if pi_cfg.get("enabled", True):
            try:
                from ai_guardian.scanners.prompt_injection import check_prompt_injection

                should_block, msg, detected = check_prompt_injection(
                    text,
                    self._config,
                )
                if detected:
                    results.append(
                        CheckResult(
                            blocked=should_block,
                            detected=True,
                            violation_type="prompt_injection",
                            message=msg,
                        )
                    )
            except Exception as e:
                logger.debug("Prompt injection check unavailable: %s", e)

        cp_cfg = self._config.get("context_poisoning", {})
        if cp_cfg.get("enabled", True):
            try:
                from ai_guardian.scanners.context_poisoning import (
                    check_context_poisoning,
                )

                should_block, msg, detected = check_context_poisoning(
                    text,
                    self._config,
                )
                if detected:
                    results.append(
                        CheckResult(
                            blocked=should_block,
                            detected=True,
                            violation_type="context_poisoning",
                            message=msg,
                        )
                    )
            except Exception as e:
                logger.debug("Context poisoning check unavailable: %s", e)

        merged = self._merge_results(results)
        return self._handle_result(merged)

    def check_file(self, file_path: str, content: Optional[str] = None) -> CheckResult:
        results = []

        try:
            from ai_guardian.hook_processing import check_directory_denied

            is_denied, denied_dir, warning_msg, pattern = check_directory_denied(
                file_path,
                self._config,
            )
            if is_denied:
                results.append(
                    CheckResult(
                        blocked=True,
                        detected=True,
                        violation_type="directory_blocked",
                        message=warning_msg or f"Access denied: {file_path}",
                    )
                )
        except Exception as e:
            logger.debug("Directory check unavailable: %s", e)

        if content is not None:
            cfg_scanner_cfg = self._config.get("config_scanner", {})
            if cfg_scanner_cfg.get("enabled", True):
                try:
                    from ai_guardian.scanners.config_scanner import (
                        check_config_file_threats,
                    )

                    should_block, msg, details = check_config_file_threats(
                        file_path,
                        content,
                        self._config,
                    )
                    if should_block:
                        results.append(
                            CheckResult(
                                blocked=True,
                                detected=True,
                                violation_type="config_file_exfil",
                                message=msg,
                                details=details,
                            )
                        )
                except Exception as e:
                    logger.debug("Config file check unavailable: %s", e)

            sc_cfg = self._config.get("supply_chain", {})
            if sc_cfg.get("enabled", True):
                try:
                    from ai_guardian.scanners.supply_chain import (
                        check_supply_chain_threats,
                    )

                    should_block, msg, details = check_supply_chain_threats(
                        file_path,
                        content,
                        self._config,
                    )
                    if should_block:
                        results.append(
                            CheckResult(
                                blocked=True,
                                detected=True,
                                violation_type="supply_chain_threat",
                                message=msg,
                                details=details,
                            )
                        )
                except Exception as e:
                    logger.debug("Supply chain check unavailable: %s", e)

            try:
                content_result = self.check_content(content, filename=file_path)
            finally:
                self._results.pop()
            if content_result.detected:
                results.append(content_result)

        merged = self._merge_results(results)
        return self._handle_result(merged)

    def check_command(self, command: str) -> CheckResult:
        results = []

        cfg_scanner_cfg = self._config.get("config_scanner", {})
        if cfg_scanner_cfg.get("enabled", True):
            try:
                from ai_guardian.scanners.config_scanner import (
                    check_bash_command_threats,
                )

                should_block, msg, details = check_bash_command_threats(
                    command,
                    self._config,
                )
                if should_block:
                    results.append(
                        CheckResult(
                            blocked=True,
                            detected=True,
                            violation_type="config_file_exfil",
                            message=msg,
                            details=details,
                        )
                    )
            except Exception as e:
                logger.debug("Command check unavailable: %s", e)

        merged = self._merge_results(results)
        return self._handle_result(merged)

    def sanitize(self, text: str) -> Dict[str, Any]:
        from ai_guardian.scanners.sanitizer import sanitize_text

        return sanitize_text(text)

    def get_violations(
        self,
        *,
        tool_use_id: Optional[str] = None,
        session_id: Optional[str] = None,
        violation_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        from ai_guardian.scanners.sanitizer import sanitize_text
        from ai_guardian.violations.logger import ViolationLogger

        limit = max(1, min(limit, 1000))
        vl = ViolationLogger(config=self._config.get("violation_logging") or {})
        raw = vl.get_recent_violations(
            limit=limit,
            violation_type=violation_type,
            tool_use_id=tool_use_id,
            session_id=session_id,
        )
        return [self._sanitize_violation(v, sanitize_text) for v in raw]


class _RestSession(GuardSession):
    """Daemon-delegated detection via socket protocol."""

    def __init__(self, action: str, config: Optional[Dict[str, Any]] = None):
        super().__init__(action, config)
        self._ensure_daemon()

    def _ensure_daemon(self):
        from ai_guardian.daemon.client import (
            is_daemon_running,
            start_daemon_background,
        )

        if not is_daemon_running():
            started = start_daemon_background()
            if not started:
                raise RuntimeError("Failed to start ai-guardian daemon")
            if not is_daemon_running():
                raise RuntimeError("Daemon started but not responding")

    def check_content(self, text: str, *, filename: str = "input") -> CheckResult:
        return self._send_check(
            "content",
            {
                "text": text,
                "filename": filename,
            },
        )

    def check_file(self, file_path: str, content: Optional[str] = None) -> CheckResult:
        data: Dict[str, Any] = {"file_path": file_path}
        if content is not None:
            data["content"] = content
        return self._send_check("file", data)

    def check_command(self, command: str) -> CheckResult:
        return self._send_check("command", {"command": command})

    def sanitize(self, text: str) -> Dict[str, Any]:
        from ai_guardian.daemon.client import send_sdk_check

        response = send_sdk_check("sanitize", {"text": text}, timeout=5.0)
        if response is None:
            return {"sanitized_text": text, "redactions": [], "stats": {}}
        return response.get("data", response)

    def get_violations(
        self,
        *,
        tool_use_id: Optional[str] = None,
        session_id: Optional[str] = None,
        violation_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        from ai_guardian.daemon.client import send_sdk_check

        params: Dict[str, Any] = {"limit": limit}
        if tool_use_id is not None:
            params["tool_use_id"] = tool_use_id
        if session_id is not None:
            params["session_id"] = session_id
        if violation_type is not None:
            params["violation_type"] = violation_type

        response = send_sdk_check("violations", params, timeout=5.0)
        if response is None:
            return []
        if response.get("error") is not None:
            logger.debug("Daemon violations query failed: %s", response["error"])
            return []
        data = response.get("data", response)
        if isinstance(data, list):
            return data
        return data.get("violations", [])

    def _send_check(self, check_type: str, data: Dict[str, Any]) -> CheckResult:
        from ai_guardian.daemon.client import send_sdk_check

        response = send_sdk_check(check_type, data, timeout=5.0)
        if response is None:
            return self._handle_result(
                CheckResult(
                    blocked=False,
                    detected=False,
                    message="Daemon unreachable",
                )
            )
        resp_data = response.get("data", response)
        return self._handle_result(
            CheckResult(
                blocked=resp_data.get("blocked", False),
                detected=resp_data.get("detected", False),
                violation_type=resp_data.get("violation_type"),
                message=resp_data.get("message"),
                details=resp_data.get("details"),
            )
        )


@contextmanager
def monitor(
    action: str = "block", mode: str = "direct", config: Optional[Dict[str, Any]] = None
):
    """Create a guarded session for security checks.

    Args:
        action: "block" (raise SecurityViolation), "warn" (warnings.warn),
                or "log" (silent recording)
        mode: "direct" (in-process, no daemon) or "rest" (daemon, auto-start)
        config: Optional config dict override. If None, loads from ai-guardian.json.

    Yields:
        GuardSession with check_content(), check_file(), check_command(),
        sanitize() methods.
    """
    if action not in ("block", "warn", "log"):
        raise ValueError(f"action must be 'block', 'warn', or 'log', got {action!r}")
    if mode not in ("direct", "rest"):
        raise ValueError(f"mode must be 'direct' or 'rest', got {mode!r}")

    if mode == "direct":
        session = _DirectSession(action=action, config=config)
    else:
        session = _RestSession(action=action, config=config)

    yield session
