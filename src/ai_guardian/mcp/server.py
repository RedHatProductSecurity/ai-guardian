#!/usr/bin/env python3
"""
AI Guardian MCP Server — read-only security advisor for AI agents.

Exposes security check tools and information queries via the Model Context
Protocol (MCP). The AI can inspect everything, change nothing.

Principle: MCP server is a security advisor, not a security map.
It says yes/no — doesn't expose security rule details.

Usage:
    ai-guardian mcp-server              # Start via stdio transport

Issue #477
"""

import json
import logging
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_SAFE_SUGGESTIONS: Dict[str, str] = {
    "secret_detected": "Remove the secret and use environment variables or a secret manager",
    "pii_detected": "Remove PII from the file or use anonymized test data",
    "directory_blocking": "This path is protected by security policy",
    "tool_permission": "This tool requires explicit permission from your admin",
    "prompt_injection": "The content contains patterns that match injection detection",
    "ssrf_blocked": "The URL targets a restricted network resource",
    "config_file_exfil": "This configuration file is protected from exfiltration",
    "jailbreak_detected": "The content contains patterns that match jailbreak detection",
    "supply_chain": "This agent configuration file contains suspicious supply chain patterns",
    "code_security": "Add # nosec or an allowlist entry in code_scanning.allowlist to suppress known-safe patterns",
    "offensive_language": "Replace the term with a neutral alternative; see the 'suggestion' field for recommended replacements",
    "canary_detected": "A registered canary token was detected — investigate potential data exfiltration",
    "exfil_detection": "This command contains credential exfiltration patterns — if legitimate, add a regex to exfil_detection.allowlist_patterns",
}

try:
    from mcp.server import MCPServer

    HAS_MCP = True
except ImportError:
    HAS_MCP = False


def _load_mcp_config() -> Dict:
    """Load ai-guardian.json and return the mcp_server section."""
    from ai_guardian.config.utils import get_config_dir

    config_path = get_config_dir() / "ai-guardian.json"
    if not config_path.exists():
        config_path = Path.cwd() / ".ai-guardian.json"
    if not config_path.exists():
        return {}
    try:
        with open(config_path, "r") as f:
            config = json.load(f)
        return config.get("mcp_server", {})
    except Exception:
        return {}


def _load_full_config() -> Optional[Dict]:
    """Load full ai-guardian.json config."""
    from ai_guardian.config.utils import get_config_dir

    config_path = get_config_dir() / "ai-guardian.json"
    if not config_path.exists():
        config_path = Path.cwd() / ".ai-guardian.json"
    if not config_path.exists():
        return None
    try:
        with open(config_path, "r") as f:
            return json.load(f)
    except Exception:
        return None


def _load_skill_instructions() -> str:
    """Load skill instructions to send during MCP initialization."""
    try:
        from importlib.resources import files as pkg_files

        skill_file = (
            pkg_files("ai_guardian") / "skills" / "ai-guardian-security" / "SKILL.md"
        )
        if hasattr(skill_file, "read_text"):
            content = skill_file.read_text()
            # Strip YAML frontmatter
            if content.startswith("---"):
                end = content.find("---", 3)
                if end != -1:
                    content = content[end + 3 :].strip()
            return content
    except Exception:
        pass  # intentionally silent — optional dependency
    return (
        "AI Guardian security advisor. Use check_path before accessing unfamiliar files, "
        "check_command before running sensitive commands, sanitize_text before outputting "
        "sensitive content. Tools are advisory — hooks provide enforcement."
    )


_BLOCKED_SYSTEM_DIRS = (
    "/etc",
    "/sys",
    "/proc",
    "/dev",
    "/boot",
    "/sbin",
    "/private/etc",
)


def _validate_scan_path(path: str) -> Tuple[bool, str, Optional[Path]]:
    """Validate a path for directory scanning.

    Returns (is_valid, error_message, resolved_path).
    Blocks system directories and non-existent paths.
    """
    try:
        resolved = Path(path).resolve()
    except Exception:
        return False, f"Invalid path: {path}", None

    if not resolved.exists():
        return False, f"Path does not exist: {path}", None

    if not resolved.is_dir():
        return False, f"Path is not a directory: {path}", None

    resolved_str = str(resolved)
    for blocked in _BLOCKED_SYSTEM_DIRS:
        if resolved_str == blocked or resolved_str.startswith(blocked + "/"):
            return False, f"Scanning system directories is not allowed: {path}", None

    return True, "", resolved


def create_server() -> "MCPServer":
    """Create and configure the MCP server with all tools and resources."""
    server = MCPServer("ai-guardian", instructions=_load_skill_instructions())

    # ─── Security Check Tools (proactive) ─────────────────────────

    _OPERATION_TO_TOOL = {"read": "Read", "write": "Write", "edit": "Edit"}

    @server.tool()
    def check_path(path: str, operation: str = "read") -> Dict[str, str]:
        """Check if a file path is protected by directory rules. Call before Read/Write/Edit on unfamiliar paths. Returns allowed/denied/not_found so you can distinguish between protected paths and missing files.

        Args:
            path: File path to check
            operation: "read", "write", or "edit" (default: "read")
        """
        try:
            resolved = Path(path).expanduser()
            if not resolved.exists():
                return {"status": "not_found"}

            from ai_guardian.tools.policy import ToolPolicyChecker

            tool_name = _OPERATION_TO_TOOL.get(operation.lower(), "Read")
            checker = ToolPolicyChecker()
            hook_data = {
                "tool_name": tool_name,
                "tool_input": {"file_path": str(resolved)},
            }
            allowed, error_msg, _ = checker.check_tool_allowed(hook_data)
            if allowed:
                return {"status": "allowed"}
            return {"status": "denied"}
        except Exception as e:
            logger.error("check_path error: %s", e)
            return {"status": "error", "message": "Unable to check path"}

    @server.tool()
    def check_command(command: str) -> Dict[str, str]:
        """Check if a Bash command would be blocked. Call before running commands with URLs or file paths. Results are advisory — hooks provide enforcement."""
        try:
            from ai_guardian.tools.policy import ToolPolicyChecker

            checker = ToolPolicyChecker()
            hook_data = {
                "tool_name": "Bash",
                "tool_input": {"command": command},
            }
            allowed, error_msg, _ = checker.check_tool_allowed(hook_data)
            if allowed:
                return {"status": "allowed"}
            reason = "policy_denied"
            if error_msg:
                msg_lower = error_msg.lower()
                if "secret" in msg_lower:
                    reason = "secret_detected"
                elif "ssrf" in msg_lower:
                    reason = "ssrf_detected"
                elif "injection" in msg_lower:
                    reason = "prompt_injection"
                elif "directory" in msg_lower or "denied" in msg_lower:
                    reason = "directory_blocked"
            return {"status": "blocked", "reason": reason}
        except Exception as e:
            logger.error("check_command error: %s", e)
            return {"status": "error", "message": "Unable to check command"}

    @server.tool()
    def check_mcp_trust(server_name: str) -> Dict[str, str]:
        """Check if an MCP server is trusted based on permission rules. Call before suggesting MCP server usage."""
        try:
            from ai_guardian.tools.policy import ToolPolicyChecker

            checker = ToolPolicyChecker()
            hook_data = {
                "tool_name": f"mcp__{server_name}__test",
                "tool_input": {},
            }
            allowed, _, _ = checker.check_tool_allowed(hook_data)
            if allowed:
                return {"status": "trusted"}
            return {"status": "untrusted"}
        except Exception as e:
            logger.error("check_mcp_trust error: %s", e)
            return {"status": "error", "message": "Unable to check MCP trust"}

    @server.tool()
    def sanitize_text(text: str) -> Dict[str, Any]:
        """Redact secrets and PII from text. Call before outputting potentially sensitive content."""
        try:
            from ai_guardian.scanners.sanitizer import sanitize_text as _sanitize

            result = _sanitize(text)
            return {
                "sanitized_text": result.get("sanitized_text", text),
                "redaction_count": result.get("stats", {}).get("total", 0),
                "types": [
                    k
                    for k, v in result.get("stats", {}).items()
                    if k != "total" and isinstance(v, int) and v > 0
                ],
            }
        except Exception as e:
            logger.error("sanitize_text error: %s", e)
            return {"sanitized_text": text, "redaction_count": 0, "types": []}

    @server.tool()
    def sanitize_directory(
        path: str,
        output_path: Optional[str] = None,
        redact_strategy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Sanitize a directory by redacting secrets and PII from all text and image files.
        Preserves directory structure in the output directory.
        Returns summary of files processed and redactions made."""
        try:
            valid, err, resolved = _validate_scan_path(path)
            if not valid:
                return {"status": "error", "message": err}

            if not resolved.is_dir():
                return {"status": "error", "message": f"Not a directory: {path}"}

            if output_path:
                out_dir = Path(output_path).resolve()
                try:
                    out_dir.relative_to(resolved)
                    return {
                        "status": "error",
                        "message": "Output directory cannot be inside source directory",
                    }
                except ValueError:
                    pass  # intentionally silent — best-effort operation
            else:
                out_dir = Path(tempfile.mkdtemp(prefix="ai-guardian-sanitized-"))
                (out_dir / ".ai-read-deny").touch()

            from ai_guardian.scanners.sanitizer import (
                sanitize_directory as _sanitize_dir,
            )

            strategy = (
                redact_strategy
                if redact_strategy in ("blur", "blackout", "pixelate")
                else "blackout"
            )
            result = _sanitize_dir(
                input_dir=resolved, output_dir=out_dir, redact_strategy=strategy
            )

            return {
                "output_path": str(out_dir),
                "text_files": result["text_files"],
                "image_files": result["image_files"],
                "binary_files": result["binary_files"],
                "skipped_files": result["skipped_files"],
                "total_redactions": result["total_redaction_count"],
                "redaction_details": result["total_redactions"],
                "errors": result["errors"],
                "message": f"Sanitized {result['text_files'] + result['image_files']} files to {out_dir}",
            }
        except Exception as e:
            logger.error("sanitize_directory error: %s", e)
            return {"status": "error", "message": "Unable to sanitize directory"}

    @server.tool()
    def check_annotations(file_path: str) -> Dict[str, Any]:
        """Verify ai-guardian annotation pairs are matched in a file. Results are advisory — hooks provide enforcement."""
        try:
            from ai_guardian.annotations import process_annotations

            path = Path(file_path)
            if not path.exists():
                return {"valid": False, "warnings": [f"File not found: {file_path}"]}
            resolved = path.resolve()
            from ai_guardian.config.utils import (
                get_config_dir,
                get_state_dir,
                get_cache_dir,
            )

            protected_dirs = (get_config_dir(), get_state_dir(), get_cache_dir())
            for pdir in protected_dirs:
                try:
                    resolved.relative_to(pdir)
                    return {"valid": False, "warnings": ["Path is protected"]}
                except ValueError:
                    pass  # intentionally silent — best-effort operation
            content = path.read_text(errors="replace")
            _, _, _, warnings = process_annotations(content, file_path)
            return {
                "valid": len(warnings) == 0,
                "warnings": warnings,
            }
        except Exception as e:
            logger.error("check_annotations error: %s", e)
            return {"valid": False, "warnings": [f"Error: {e}"]}

    # ─── Information Tools (query) ────────────────────────────────

    @server.tool()
    def get_violations(
        violation_type: Optional[str] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """Get recent security violations. Filter by type (secret_detected, prompt_injection, directory_blocking, tool_permission, ssrf_blocked, config_file_exfil, pii_detected, jailbreak_detected)."""
        try:
            from ai_guardian.violations.logger import ViolationLogger

            vl = ViolationLogger()
            violations = vl.get_recent_violations(
                limit=min(limit, 100),
                violation_type=violation_type,
            )
            filtered = []
            for v in violations:
                if v.get("violation_type") == "annotation_suppressed":
                    continue
                blocked = v.get("blocked", {})
                if not isinstance(blocked, dict):
                    blocked = {}
                vtype = v.get("violation_type", "")
                ctx = v.get("context", {})
                if not isinstance(ctx, dict):
                    ctx = {}
                entry = {
                    "timestamp": v.get("timestamp", ""),
                    "type": vtype,
                    "severity": v.get("severity", ""),
                    "tool": ctx.get("tool_name", "") or blocked.get("tool", ""),
                    "file": blocked.get("file_path", "") or ctx.get("file_path", ""),
                    "action": "blocked" if v.get("blocked") else "logged",
                    "suggestion": _SAFE_SUGGESTIONS.get(
                        vtype, "Review the security policy for this violation type"
                    ),
                }
                if ctx.get("source"):
                    entry["source"] = ctx["source"]
                if blocked.get("line_number"):
                    entry["line"] = blocked["line_number"]
                if blocked.get("start_column") is not None:
                    entry["start_column"] = blocked["start_column"] + 1
                if blocked.get("end_column") is not None:
                    entry["end_column"] = blocked["end_column"] + 1
                filtered.append(entry)
            return {"violations": filtered, "count": len(filtered)}
        except Exception as e:
            logger.error("get_violations error: %s", e)
            return {"violations": [], "count": 0}

    @server.tool()
    def get_config() -> Dict[str, Any]:
        """Get current security posture summary. Returns feature enabled/disabled status only — no security rule details. Re-reads config on every call to reflect changes."""
        try:
            from ai_guardian.config.utils import is_feature_enabled

            config = _load_full_config() or {}
            features = {}

            feature_keys = [
                "secret_scanning",
                "scan_pii",
                "prompt_injection",
                "config_scanning",
                "violation_logging",
                "ssrf_protection",
                "secret_redaction",
                "transcript_scanning",
                "image_scanning",
                "supply_chain",
            ]
            for key in feature_keys:
                section = config.get(key, {})
                if isinstance(section, dict):
                    features[key] = is_feature_enabled(section.get("enabled", True))
                else:
                    features[key] = bool(section) if section is not None else True

            features["permissions"] = config.get("permissions", {}).get("enabled", True)

            si_section = config.get("security_instructions", {})
            features["security_instructions"] = is_feature_enabled(
                (
                    si_section.get("inject_on_prompt")
                    if isinstance(si_section, dict)
                    else None
                ),
                default=True,
            )

            scanner_action_keys = [
                "secret_redaction",
                "scan_pii",
                "prompt_injection",
                "context_poisoning",
                "ssrf_protection",
                "supply_chain",
                "config_file_scanning",
            ]
            global_action = config.get("action", "block")
            scanner_actions = {}
            for key in scanner_action_keys:
                section = config.get(key, {})
                if isinstance(section, dict):
                    scanner_actions[key] = section.get("action", global_action)
                else:
                    scanner_actions[key] = global_action
            features["scanner_actions"] = scanner_actions

            mcp_section = config.get("mcp_server", {})
            features["mcp_server"] = True
            features["proactive_level"] = mcp_section.get("proactive_level", "low")

            from ai_guardian.config.utils import get_project_config_path

            project_path = get_project_config_path()
            features["project_config"] = str(project_path) if project_path else None

            return {"features": features}
        except Exception as e:
            logger.error("get_config error: %s", e)
            return {"features": {}}

    @server.tool()
    def get_scanner_status() -> Dict[str, Any]:
        """Get installed scanner engines and their versions."""
        try:
            from ai_guardian.scanners.manager import ScannerManager

            sm = ScannerManager()
            installed = sm.list_installed()
            scanners = [
                {
                    "name": s.name,
                    "version": s.version,
                    "is_default": s.is_default,
                }
                for s in installed
            ]
            return {"scanners": scanners, "count": len(scanners)}
        except Exception as e:
            logger.error("get_scanner_status error: %s", e)
            return {"scanners": [], "count": 0}

    @server.tool()
    def get_scanner_supported() -> Dict[str, Any]:
        """Get all supported scanner engines that can be installed."""
        try:
            from ai_guardian.scanners.manager import ScannerManager

            return {"scanners": list(ScannerManager.SUPPORTED_SCANNERS)}
        except Exception as e:
            logger.error("get_scanner_supported error: %s", e)
            return {"scanners": []}

    @server.tool()
    def get_patterns_list() -> Dict[str, Any]:
        """Get active detection pattern categories and counts. Returns category names and pattern counts only — no regex patterns."""
        try:
            from ai_guardian.patterns.lister import PatternLister

            lister = PatternLister()
            categories = lister.get_categories()
            result = {}
            for cat in categories:
                count = sum(g.count for g in cat.built_in_groups)
                if count > 0:
                    result[cat.name] = count
            return {"categories": result}
        except Exception as e:
            logger.error("get_patterns_list error: %s", e)
            return {"categories": {}}

    @server.tool()
    def get_metrics(since_days: Optional[int] = None) -> Dict[str, Any]:
        """Get violation statistics and trends. Optionally filter to last N days."""
        try:
            from ai_guardian.reporting.metrics import MetricsComputer

            mc = MetricsComputer(since_days=since_days)
            report = mc.compute()
            return {
                "total_violations": report.total_violations,
                "by_type": dict(report.by_type),
                "by_severity": dict(report.by_severity),
                "resolved": report.resolved_count,
                "unresolved": report.unresolved_count,
                "cumulative_total": report.cumulative_total,
                "cumulative_by_type": dict(report.cumulative_by_type),
                "cumulative_since": report.cumulative_since,
            }
        except Exception as e:
            logger.error("get_metrics error: %s", e)
            return {"total_violations": 0, "by_type": {}, "by_severity": {}}

    @server.tool()
    def doctor() -> Dict[str, Any]:
        """Run health check on ai-guardian setup. Returns check results with pass/warn/fail status."""
        try:
            from ai_guardian.doctor import Doctor

            doc = Doctor()
            report = doc.run_all()
            checks = []
            for c in report.checks:
                entry = {
                    "name": c.name,
                    "status": c.status.value,
                    "message": c.message,
                }
                if c.status.value in ("warn", "fail"):
                    if c.detail:
                        entry["detail"] = c.detail
                    if c.fix_hint:
                        entry["fix_hint"] = c.fix_hint
                    entry["fixable"] = c.fixable
                checks.append(entry)
            return {
                "checks": checks,
                "has_errors": report.has_errors,
                "has_warnings": report.has_warnings,
            }
        except Exception as e:
            logger.error("doctor error: %s", e)
            return {"checks": [], "has_errors": True, "has_warnings": False}

    # ─── Support Bundle Tools ─────────────────────────────────────

    @server.tool()
    def prepare_support_bundle() -> Dict[str, Any]:
        """Prepare a sanitized support bundle for review. Creates a protected temp directory with sanitized copies of config, violations, metrics, doctor results, system info, and log. IMPORTANT: After calling this, you MUST (1) show the temp_path so the user can review and delete unwanted files, (2) present the file list with redaction counts, and (3) wait for the user to confirm before calling send_support_bundle. Only the user can access the temp directory — do not try to read or delete files in it."""
        try:
            from ai_guardian.reporting.support_bundle import prepare_bundle

            return prepare_bundle()
        except Exception as e:
            logger.error("prepare_support_bundle error: %s", e)
            return {"status": "error", "message": f"Failed to prepare bundle: {e}"}

    @server.tool()
    def send_support_bundle(bundle_id: str) -> Dict[str, Any]:
        """Send a previously prepared support bundle to the preconfigured destination. Only call after the user has reviewed the temp directory, deleted any unwanted files, and explicitly approved sending. After sending, tell the user to contact support and give them the bundle_id as their reference number."""
        try:
            from ai_guardian.reporting.support_bundle import send_bundle

            return send_bundle(bundle_id)
        except Exception as e:
            logger.error("send_support_bundle error: %s", e)
            return {"status": "error", "message": f"Failed to send bundle: {e}"}

    # ─── Scanning Tools ──────────────────────────────────────────

    @server.tool()
    def scan_directory(path: str = ".", recursive: bool = True) -> Dict[str, Any]:
        """Scan a directory for secrets, PII, and security issues.
        Returns summary only — no actual secret/PII values."""
        try:
            valid, err, resolved = _validate_scan_path(path)
            if not valid:
                return {"status": "error", "message": err}

            from ai_guardian.scanners.file_scanner import FileScanner

            config = _load_full_config() or {}
            scanner = FileScanner(config=config)

            start_ms = time.monotonic_ns() // 1_000_000
            findings = scanner.scan_directory(path=str(resolved))
            elapsed_ms = (time.monotonic_ns() // 1_000_000) - start_ms

            by_type: Dict[str, int] = {}
            for f in findings:
                rule = f.get("rule_id", "unknown")
                by_type[rule] = by_type.get(rule, 0) + 1

            file_count = (
                len(scanner._discover_files(resolved, None, None, False))
                if resolved.is_dir()
                else 1
            )

            return {
                "scanned_files": file_count,
                "violations": len(findings),
                "by_type": by_type,
                "scan_time_ms": elapsed_ms,
            }
        except Exception as e:
            logger.error("scan_directory error: %s", e)
            return {"status": "error", "message": "Unable to scan directory"}

    @server.tool()
    def scan_directory_report(path: str = ".", format: str = "json") -> Dict[str, Any]:
        """Generate a detailed scan report in a temp directory for user review.

        Args:
            path: Directory to scan
            format: json or sarif

        Returns:
            Path to report file (user reviews directly — AI doesn't see content)
        """
        try:
            valid, err, resolved = _validate_scan_path(path)
            if not valid:
                return {"status": "error", "message": err}

            if format not in ("json", "sarif"):
                return {
                    "status": "error",
                    "message": f"Unsupported format: {format}. Use 'json' or 'sarif'.",
                }

            from ai_guardian.scanners.file_scanner import FileScanner

            config = _load_full_config() or {}
            scanner = FileScanner(config=config)
            findings = scanner.scan_directory(path=str(resolved))

            report_dir = tempfile.mkdtemp(prefix="ai-guardian-scan-report-")
            (Path(report_dir) / ".ai-read-deny").touch()

            if format == "sarif":
                from ai_guardian import __version__
                from ai_guardian.reporting.sarif import SARIFFormatter

                formatter = SARIFFormatter(version=__version__)
                report_file = str(Path(report_dir) / "scan-results.sarif")
                formatter.write_sarif_file(
                    findings, report_file, scan_path=str(resolved)
                )
            else:
                report_file = str(Path(report_dir) / "scan-results.json")
                with open(report_file, "w", encoding="utf-8") as f:
                    json.dump(findings, f, indent=2)

            return {
                "report_path": report_file,
                "violations": len(findings),
                "format": format,
                "message": f"Detailed report generated. Review at: {report_dir}/",
            }
        except Exception as e:
            logger.error("scan_directory_report error: %s", e)
            return {
                "status": "error",
                "message": "Unable to generate scan report",
            }

    # ─── Resources ────────────────────────────────────────────────

    @server.resource("ai-guardian://security-posture")
    def security_posture() -> str:
        """Summary of enabled security features, action modes, and scanner status."""
        try:
            features = get_config()
            scanners = get_scanner_status()
            result = {
                "features": features.get("features", {}),
                "scanners": scanners.get("scanners", []),
            }
            return json.dumps(result, indent=2)
        except Exception:
            return json.dumps({"error": "Unable to load security posture"})

    @server.resource("ai-guardian://protected-paths")
    def protected_paths() -> str:
        """List of protected directories (paths only, no rules)."""
        try:
            import os

            cwd = Path.cwd()
            protected = []
            for root, dirs, files in os.walk(cwd):
                if ".ai-read-deny" in files:
                    protected.append(str(Path(root).relative_to(cwd)))
                dirs[:] = [
                    d
                    for d in dirs
                    if d not in {".git", "node_modules", "__pycache__", ".venv", "venv"}
                ]
            return json.dumps({"protected_directories": protected})
        except Exception:
            return json.dumps({"protected_directories": []})

    @server.resource("ai-guardian://recent-violations")
    def recent_violations() -> str:
        """Last 10 security violations with details."""
        try:
            result = get_violations(limit=10)
            return json.dumps(result, indent=2)
        except Exception:
            return json.dumps({"violations": [], "count": 0})

    return server


def run_mcp_server() -> int:
    """Start the MCP server via stdio transport. Called by CLI: ai-guardian mcp-server."""
    if not HAS_MCP:
        print(
            "Error: MCP SDK not available (requires Python >= 3.10).",
            file=sys.stderr,
        )
        return 1

    server = create_server()
    server.run(transport="stdio")
    return 0
