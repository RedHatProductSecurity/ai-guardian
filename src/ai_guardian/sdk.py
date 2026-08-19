"""
AI Guardian SDK — programmatic security checking for Python agent programs.

Provides opt-in protection for programs where IDE hooks don't apply
(LangChain, custom scripts, direct LLM API calls, etc.).

This SDK is additive — it cannot bypass or weaken existing hook-based
enforcement. Hooks remain the enforcement layer for IDE sessions.

Usage:
    from ai_guardian.sdk import monitor

    # Direct mode (default) — in-process, no daemon
    with monitor() as session:
        session.check_content(text)
        session.check_file("/path/to/file")
        session.check_command("curl http://example.com")

    # REST mode — delegates to daemon, auto-starts if needed
    with monitor(mode="rest") as session:
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
    violation_id: Optional[str] = None
    message: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class SecurityViolation(Exception):
    """Raised when a blocked finding is detected."""

    def __init__(
        self,
        result: CheckResult,
        sanitized_text=None,
        response=None,
        sanitized_parsed=None,
    ):
        self.result = result
        self.sanitized_text = sanitized_text
        self.response = response
        self.sanitized_parsed = sanitized_parsed
        msg = result.message or "Security violation detected"
        if result.violation_id:
            msg += f" (Violation ID: {result.violation_id})"
        super().__init__(msg)


class _SecurityWarning(UserWarning):
    """Warning category for detected-but-not-blocked findings."""

    pass


class GuardSession:
    """Base session with shared action-handling logic."""

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        target_dir: Optional[str] = None,
    ):
        self._config = config
        self._target_dir = target_dir
        self._results: List[CheckResult] = []
        self._secret_redaction_enabled: bool = False

    @property
    def results(self) -> List[CheckResult]:
        """All results collected during this session."""
        return list(self._results)

    @property
    def secret_redaction_enabled(self) -> bool:
        """Whether to redact secrets in live content (not traces).

        SDK defaults to ``False`` — content flows unchanged between agent
        turns.  Set to ``True`` via config to sanitize content same as hooks.
        Trace sanitization is independent of this flag.
        """
        return self._secret_redaction_enabled

    def check_content(
        self,
        text: str,
        *,
        filename: str = "input",
        source_command: Optional[str] = None,
    ) -> CheckResult:
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

    def sanitize_batch(self, texts: List[str]) -> List[str]:
        """Batch-sanitize texts, reusing compiled patterns across all entries.

        Returns sanitized strings in the same order as *texts*.
        Default implementation loops over :meth:`sanitize`; subclasses
        override to amortize pattern compilation.
        """
        results = []
        for text in texts:
            if not text:
                results.append(text)
                continue
            try:
                result = self.sanitize(text)
                results.append(result.get("sanitized_text", text))
            except Exception:
                results.append(text)
        return results

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
        if result.blocked:
            raise SecurityViolation(result)
        if result.detected:
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
        ids = [r.violation_id for r in results if r.violation_id]
        merged_details = (
            {
                "individual_results": [
                    {
                        "violation_type": r.violation_type,
                        "violation_id": r.violation_id,
                        "message": r.message,
                    }
                    for r in results
                    if r.detected
                ]
            }
            if len(results) > 1 and detected
            else (results[0].details if results else None)
        )
        return CheckResult(
            blocked=blocked,
            detected=detected,
            violation_type=(
                types[0] if len(types) == 1 else (",".join(types) if types else None)
            ),
            violation_id=ids[0] if len(ids) == 1 else None,
            message="; ".join(messages) if messages else None,
            details=merged_details,
        )


class _DirectSession(GuardSession):
    """In-process detection — calls detection functions directly."""

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        cwd: Optional[str] = None,
        target_dir: Optional[str] = None,
    ):
        super().__init__(config, target_dir=target_dir)
        self._cwd = cwd
        self._ensure_config()
        self._register_project_with_daemon()

    def _ensure_config(self):
        if self._config is None:
            from ai_guardian.config.loaders import (
                _load_config_file,
                _sdk_secret_redaction_enabled,
                _sdk_use_global_config,
            )
            from ai_guardian.config.utils import (
                clear_project_dir_override,
                set_project_dir_override,
                _clear_project_config_cache,
            )

            if self._cwd:
                set_project_dir_override(self._cwd)
                _clear_project_config_cache()

            try:
                if _sdk_use_global_config():
                    cfg, _ = _load_config_file()
                    self._config = cfg or {}
                else:
                    self._config = {}
                self._secret_redaction_enabled = _sdk_secret_redaction_enabled(
                    self._config
                )
            finally:
                if self._cwd:
                    clear_project_dir_override()
                    _clear_project_config_cache()
        else:
            from ai_guardian.config.loaders import _sdk_secret_redaction_enabled

            self._secret_redaction_enabled = _sdk_secret_redaction_enabled(self._config)

        if self._target_dir:
            from ai_guardian.config.target_config import merge_target_allowlists

            self._config = merge_target_allowlists(self._config, self._target_dir)

    def _register_project_with_daemon(self):
        """Register project CWD with daemon for project-scoped scanning."""
        import os as _os

        cwd = self._cwd or _os.getcwd()
        try:
            import json as _json

            from ai_guardian.daemon import get_pid_path

            pid_path = get_pid_path()
            if not pid_path.exists():
                return
            pid_info = _json.loads(pid_path.read_text())
            rest_port = pid_info.get("rest_port")
            if not rest_port:
                return

            from urllib.request import Request, urlopen

            payload = _json.dumps({"project_dir": cwd}).encode("utf-8")
            req = Request(
                f"http://127.0.0.1:{rest_port}/api/register-project",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            auth_token = pid_info.get("auth_token")
            if auth_token:
                req.add_header("Authorization", f"Bearer {auth_token}")
            urlopen(req, timeout=2)
        except Exception:
            logger.debug("Failed to register project with daemon", exc_info=True)

    def _log_scan_results(self, scan_results):
        """Log detected violations via unified log_violation (fixes #2019)."""
        detected = [r for r in scan_results if r.detected]
        if not detected:
            return
        try:
            import os

            from ai_guardian.violations.log_violation import (
                ScanContext,
                log_violations,
            )

            ctx = ScanContext(
                ide_type="sdk",
                project_path=self._cwd or os.getcwd(),
            )
            log_violations(detected, ctx)
        except Exception as e:
            logger.debug("SDK violation logging failed: %s", e)

    def check_content(
        self,
        text: str,
        *,
        filename: str = "input",
        source_command: Optional[str] = None,
    ) -> CheckResult:
        from ai_guardian.scanners.pipeline import scan_content

        scan_results = scan_content(
            text,
            config=self._config,
            cwd=self._cwd,
            filename=filename,
            source_type="file_content",
            source_command=source_command,
        )

        self._log_scan_results(scan_results)

        results = [
            CheckResult(
                blocked=r.should_block,
                detected=r.detected,
                violation_type=r.violation_type,
                violation_id=r.id,
                message=r.error_message,
            )
            for r in scan_results
        ]

        merged = self._merge_results(results)
        return self._handle_result(merged)

    def check_file(self, file_path: str, content: Optional[str] = None) -> CheckResult:
        from ai_guardian.scanners.pipeline import scan_file

        scan_results = scan_file(
            file_path,
            content=content,
            config=self._config,
            cwd=self._cwd,
        )

        self._log_scan_results(scan_results)

        results = [
            CheckResult(
                blocked=r.should_block,
                detected=r.detected,
                violation_type=r.violation_type,
                violation_id=r.id,
                message=r.error_message,
            )
            for r in scan_results
        ]

        merged = self._merge_results(results)
        return self._handle_result(merged)

    def check_command(self, command: str) -> CheckResult:
        from ai_guardian.scanners.pipeline import scan_command

        scan_results = scan_command(command, config=self._config)

        self._log_scan_results(scan_results)

        results = [
            CheckResult(
                blocked=r.should_block,
                detected=r.detected,
                violation_type=r.violation_type,
                violation_id=r.id,
                message=r.error_message,
            )
            for r in scan_results
        ]

        merged = self._merge_results(results)
        return self._handle_result(merged)

    def sanitize(self, text: str) -> Dict[str, Any]:
        from ai_guardian.scanners.sanitizer import sanitize_text

        return sanitize_text(text)

    def sanitize_batch(self, texts: List[str]) -> List[str]:
        from ai_guardian.scanners.sanitizer import sanitize_text_batch

        return sanitize_text_batch(texts)

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

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        cwd: Optional[str] = None,
        target_dir: Optional[str] = None,
    ):
        super().__init__(config, target_dir=target_dir)
        self._cwd = cwd
        if target_dir:
            logger.warning(
                "target_dir=%s not yet supported in REST mode — "
                "allowlists will not be merged",
                target_dir,
            )
        self._resolve_redaction_flag()
        self._ensure_daemon()

    def _resolve_redaction_flag(self):
        from ai_guardian.config.loaders import _sdk_secret_redaction_enabled

        self._secret_redaction_enabled = _sdk_secret_redaction_enabled(self._config)

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
    mode: str = "direct",
    config: Optional[Dict[str, Any]] = None,
    cwd: Optional[str] = None,
    target_dir: Optional[str] = None,
    **kwargs,
):
    """Create a guarded session for security checks.

    Blocked findings raise ``SecurityViolation``; detected-but-not-blocked
    findings emit ``warnings.warn``.  Per-scanner actions in the global
    config control which findings are blocked vs. detected.

    Args:
        mode: "direct" (in-process, no daemon) or "rest" (daemon, auto-start)
        config: Optional config dict override. If None, loads from ai-guardian.json
                (respects ``sdk.use_global_config``).
        cwd: Project directory for config discovery and language detection.
             If None, falls back to os.getcwd().
        target_dir: Directory whose allowlists to trust.  When set,
            ai-guardian discovers ``.ai-guardian/ai-guardian.json``,
            ``.aiguardignore.toml``, and ``.gitleaks.toml`` in
            *target_dir* and merges their suppression data (allowlist
            patterns, ignore files/tools) into the running config.
            Separate from *cwd* — ``cwd`` is where to run tools,
            ``target_dir`` is whose allowlists to apply.

    Yields:
        GuardSession with check_content(), check_file(), check_command(),
        sanitize() methods.
    """
    if "action" in kwargs:
        import warnings as _w

        _w.warn(
            "monitor(action=...) is deprecated and ignored. "
            "Per-scanner actions in config control blocking.",
            DeprecationWarning,
            stacklevel=2,
        )
    if "scan" in kwargs:
        import warnings as _w

        _w.warn(
            "monitor(scan=...) is deprecated and ignored.",
            DeprecationWarning,
            stacklevel=2,
        )
    unknown = set(kwargs) - {"action", "scan"}
    if unknown:
        raise TypeError(
            f"monitor() got unexpected keyword argument(s): {', '.join(sorted(unknown))}"
        )
    if mode not in ("direct", "rest"):
        raise ValueError(f"mode must be 'direct' or 'rest', got {mode!r}")

    if mode == "direct":
        session = _DirectSession(config=config, cwd=cwd, target_dir=target_dir)
    else:
        session = _RestSession(config=config, cwd=cwd, target_dir=target_dir)

    yield session
