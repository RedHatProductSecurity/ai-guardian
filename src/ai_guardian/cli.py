"""
CLI entry point for AI Guardian.

Contains the main() function with argparse setup and all subcommand handlers.
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from ai_guardian import __version__
from ai_guardian.constants import ViolationType

from ai_guardian.config.loaders import (
    _load_config_file,
)


from ai_guardian.hook_processing import (
    process_hook_data,
    process_hook_input,
    HAS_VIOLATION_LOGGER,
)
from ai_guardian.cli_handlers import (
    _handle_violations_command,
    _get_client_timeout,
    _handle_daemon_command,
    _handle_tray_command,
    _handle_prompt,
    _handle_tray_target_select,
)

logger = logging.getLogger(__name__)


def _is_stop_requested():
    """Check if daemon was explicitly stopped and should not be auto-started.

    The marker is written by ``daemon stop`` and cleared by ``daemon start``.
    """
    try:
        from ai_guardian.daemon import get_state_dir

        marker = get_state_dir() / "daemon.stop-requested"
        return marker.exists()
    except Exception:
        pass  # intentionally silent — optional dependency
    return False


def _ensure_daemon_started():
    """Auto-start daemon if not running. Silent — no output on success or failure."""
    try:
        if _is_stop_requested():
            logger.debug("Skipping daemon auto-start: recent stop requested")
            return

        from ai_guardian.daemon.client import is_daemon_running, start_daemon_background

        if not is_daemon_running():
            start_daemon_background()
    except Exception:
        pass  # intentionally silent — best-effort operation

    try:
        from ai_guardian.daemon.auto_setup import auto_setup_tray

        auto_setup_tray()
    except Exception:
        pass  # intentionally silent — best-effort operation


def _handle_ml_command(args, ml_parser):
    """Handle ML model management subcommands."""
    cmd = getattr(args, "ml_command", None)

    if cmd is None:
        ml_parser.print_help()
        return 1

    if cmd == "setup":
        from ai_guardian.scanners.ml_detection import setup_ml

        result = setup_ml(
            detector=args.detector,
            model=args.model,
            threshold=args.threshold,
            force=args.force,
        )

        for step_name, ok, msg in result["steps"]:
            status = "ok" if ok else "FAILED"
            print(f"  [{status}] {step_name}: {msg}")

        if result["success"]:
            print()
            print("ML prompt injection detection is ready.")
            print("Restart the daemon to load the model: ai-guardian daemon restart")
            return 0
        else:
            print()
            print("Setup incomplete. See errors above.", file=sys.stderr)
            return 1

    elif cmd == "download":
        from ai_guardian.scanners.ml_detection import is_ml_available, download_model

        if not is_ml_available():
            print(
                "Error: ML dependencies not available (onnxruntime required).",
                file=sys.stderr,
            )
            return 1
        try:
            model_dir = download_model(model_name=args.model, force=args.force)
            print(f"Model downloaded to: {model_dir}")
            return 0
        except Exception as e:
            print(f"Error downloading model: {e}", file=sys.stderr)
            return 1

    elif cmd == "list":
        from ai_guardian.scanners.ml_detection import (
            is_ml_available,
            list_registered_models,
        )

        print("ML Dependencies:", "installed" if is_ml_available() else "NOT installed")
        print()
        models = list_registered_models()
        for m in models:
            status = "downloaded" if m["downloaded"] else "not downloaded"
            print(f"  {m['name']}")
            print(f"    Status: {status}")
            print(f"    Description: {m['description']}")
            if m["path"]:
                print(f"    Path: {m['path']}")
            print()
        if not models:
            print("  No models in registry")
        return 0

    elif cmd == "status":
        from ai_guardian.scanners.ml_detection import (
            is_ml_available,
            verify_model,
            get_models_dir,
        )

        print(f"ML dependencies installed: {is_ml_available()}")
        print(f"Models directory: {get_models_dir()}")
        is_valid, msg = verify_model()
        print(f"Default model valid: {is_valid}")
        print(f"  {msg}")

        try:
            from ai_guardian.daemon.client import is_daemon_running, send_status_request

            if is_daemon_running():
                status = send_status_request()
                if status:
                    print(
                        f"\nDaemon ML model loaded: {status.get('ml_model_loaded', False)}"
                    )
                    ml_err = status.get("ml_load_error")
                    if ml_err:
                        print(f"  Load error: {ml_err}")
            else:
                print("\nDaemon: not running")
        except Exception:
            print("\nDaemon: status unavailable")
        return 0

    elif cmd == "verify":
        from ai_guardian.scanners.ml_detection import verify_model

        is_valid, msg = verify_model(args.model)
        print(msg)
        return 0 if is_valid else 1

    else:
        ml_parser.print_help()
        return 1


def main():
    """Main entry point for the hook."""
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass  # intentionally silent — encoding reconfigure best-effort

    # If arguments are provided, handle them
    if len(sys.argv) > 1:
        parser = argparse.ArgumentParser(
            prog="ai-guardian",
            description="AI IDE security hook for blocking directories and scanning secrets",
        )
        parser.add_argument(
            "--version",
            "-v",
            action="version",
            version=f"ai-guardian {__version__}",
        )
        parser.add_argument(
            "--ide",
            choices=[
                "claude",
                "cursor",
                "copilot",
                "codex",
                "windsurf",
                "gemini",
                "cline",
                "zoocode",
                "augment",
                "kiro",
                "junie",
                "aiderdesk",
                "openclaw",
                "opencode",
            ],
            help="Specify IDE adapter for hook processing (auto-detected if not provided)",
        )

        # Add subcommands
        subparsers = parser.add_subparsers(dest="command", help="Available commands")

        # Setup subcommand
        setup_parser = subparsers.add_parser(
            "setup", help="Setup IDE hooks with optional remote config"
        )
        setup_parser.add_argument(
            "--ide",
            choices=[
                "claude",
                "cursor",
                "copilot",
                "codex",
                "windsurf",
                "gemini",
                "cline",
                "zoocode",
                "augment",
                "kiro",
                "junie",
                "aiderdesk",
                "openclaw",
                "opencode",
            ],
            help="Specify IDE type (auto-detected if not provided)",
        )
        setup_parser.add_argument(
            "--remote-config-url", metavar="URL", help="Remote configuration URL to add"
        )
        setup_parser.add_argument(
            "--migrate-pattern-server",
            action="store_true",
            help="Migrate pattern_server config to per-engine format (moves global to engines[].pattern_server)",
        )
        setup_parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be changed without applying",
        )
        setup_parser.add_argument(
            "--force", action="store_true", help="Overwrite existing hooks and config"
        )
        setup_parser.add_argument(
            "--yes", "-y", action="store_true", help="Skip confirmation prompts"
        )
        setup_parser.add_argument(
            "--create-config",
            action="store_true",
            help="Create default ai-guardian.json config file",
        )
        setup_parser.add_argument(
            "--permissive",
            action="store_true",
            help="Use permissive config (permissions disabled, all tools allowed)",
        )
        setup_parser.add_argument(
            "--pre-commit",
            action="store_true",
            help="Install pre-commit hooks for git workflow",
        )
        setup_parser.add_argument(
            "--auto-install-hooks",
            action="store_true",
            help="Allow automatic hook installation (default: show instructions only)",
        )
        setup_parser.add_argument(
            "--uninstall-hooks",
            action="store_true",
            help="Remove AI Guardian pre-commit hooks",
        )
        setup_parser.add_argument(
            "--install-scanner",
            nargs="*",
            choices=["gitleaks", "betterleaks", "leaktk"],
            help="Install scanner engine(s) (default: gitleaks). "
            "Accepts multiple: --install-scanner gitleaks betterleaks",
        )
        setup_parser.add_argument(
            "--use-pinned",
            action="store_true",
            help="Install pinned scanner version from pyproject.toml (use with --install-scanner)",
        )
        setup_parser.add_argument(
            "--json",
            action="store_true",
            dest="json_output",
            help="Output only raw JSON config (use with --create-config)",
        )
        setup_parser.add_argument(
            "--profile",
            metavar="PROFILE",
            help="Security profile to apply: @minimal, @standard, @strict, @moderator, custom name, or file path (use with --create-config)",
        )
        setup_parser.add_argument(
            "--save-profile",
            metavar="NAME",
            help="Save current config as a named custom profile",
        )
        setup_parser.add_argument(
            "--list-profiles",
            action="store_true",
            help="List available security profiles (built-in and custom)",
        )
        setup_parser.add_argument(
            "--no-mcp",
            action="store_true",
            default=None,
            help="Skip MCP server installation (MCP is installed by default)",
        )
        setup_parser.add_argument(
            "--rules",
            action="store_true",
            default=None,
            help="Install AI guidelines/rules file instructing the agent to use ai-guardian MCP tools",
        )

        # Violations subcommand
        violations_parser = subparsers.add_parser(
            "violations", help="View and manage violation log"
        )
        violations_parser.add_argument(
            "--type", choices=list(ViolationType), help="Filter by violation type"
        )
        violations_parser.add_argument(
            "--limit",
            type=int,
            default=10,
            help="Number of violations to show (default: 10)",
        )
        violations_parser.add_argument(
            "--clear", action="store_true", help="Clear all violations from log"
        )
        violations_parser.add_argument(
            "--export", metavar="FILE", help="Export violations to JSON file"
        )
        violations_parser.add_argument(
            "--yes",
            "-y",
            action="store_true",
            help="Skip confirmation prompt (for non-interactive use)",
        )

        # Metrics subcommand (Issue #469, #476)
        metrics_parser = subparsers.add_parser(
            "metrics", help="Show violation statistics, trends, and compliance audit"
        )
        metrics_parser.add_argument(
            "--json", action="store_true", help="Output as JSON"
        )
        metrics_parser.add_argument(
            "--csv", action="store_true", help="Export filtered violations as CSV"
        )
        metrics_parser.add_argument(
            "--html",
            action="store_true",
            help="Output self-contained HTML audit report",
        )
        metrics_parser.add_argument(
            "--since",
            default="30d",
            help="Time range start: Nd for days (e.g. 30d) or ISO date (e.g. 2026-05-01). Default: 30d",
        )
        metrics_parser.add_argument(
            "--until", default=None, help="Time range end: Nd or ISO date. Default: now"
        )
        metrics_parser.add_argument(
            "--type", choices=list(ViolationType), help="Filter by violation type"
        )
        metrics_parser.add_argument(
            "--severity",
            choices=["warning", "high", "critical"],
            help="Filter by severity level",
        )
        metrics_parser.add_argument(
            "--latency",
            action="store_true",
            help="Show hook latency statistics (avg, stddev, P95, min, max)",
        )
        metrics_parser.add_argument(
            "--reset",
            action="store_true",
            help="Reset cumulative counters to current log file counts",
        )
        metrics_parser.add_argument(
            "--yes",
            "-y",
            action="store_true",
            dest="metrics_yes",
            help="Skip confirmation prompt for --reset",
        )

        # Console subcommand (primary)
        console_parser = subparsers.add_parser(
            "console", help="Launch interactive console for configuration management, use --web for web console in browser (Python >= 3.10 required)"
        )
        console_parser.add_argument(
            "--panel",
            help="Open a specific panel (e.g., 'panel-violations', 'panel-daemon')",
        )
        console_parser.add_argument(
            "--web",
            action="store_true",
            help="Launch web console in browser instead of TUI (requires Python >= 3.10)",
        )
        console_parser.add_argument(
            "--port",
            type=int,
            default=0,
            help="Port for web console (default: auto-assign, only used with --web)",
        )
        console_parser.add_argument(
            "--no-open",
            action="store_true",
            help="Don't open browser automatically (only used with --web)",
        )

        # TUI subcommand (alias for console, kept for backward compatibility)
        tui_parser = subparsers.add_parser(
            "tui", help="Launch interactive console (alias for ai-guardian console)"
        )
        tui_parser.add_argument(
            "--panel",
            help="Open a specific panel (e.g., 'panel-violations', 'panel-daemon')",
        )
        tui_parser.add_argument(
            "--web",
            action="store_true",
            help="Launch web console in browser instead of TUI (requires Python >= 3.10)",
        )
        tui_parser.add_argument(
            "--port",
            type=int,
            default=0,
            help="Port for web console (default: auto-assign, only used with --web)",
        )
        tui_parser.add_argument(
            "--no-open",
            action="store_true",
            help="Don't open browser automatically (only used with --web)",
        )

        # Scan subcommand
        scan_parser = subparsers.add_parser(
            "scan", help="Scan repository files for security issues"
        )
        scan_parser.add_argument(
            "path",
            nargs="?",
            default=None,
            help="Path to scan (file or directory, default: current directory). Use '--' to read from stdin.",
        )
        scan_parser.add_argument(
            "--text",
            metavar="STRING",
            help="Scan inline text string for security issues",
        )
        scan_parser.add_argument(
            "--config", metavar="FILE", help="Path to ai-guardian.json config file"
        )
        scan_parser.add_argument(
            "--include",
            action="append",
            metavar="PATTERN",
            help="File patterns to include (glob style, can be specified multiple times)",
        )
        scan_parser.add_argument(
            "--exclude",
            action="append",
            metavar="PATTERN",
            help="File patterns to exclude (glob style, can be specified multiple times)",
        )
        scan_parser.add_argument(
            "--config-only",
            action="store_true",
            help="Only scan AI config files (CLAUDE.md, AGENTS.md, etc.)",
        )
        scan_parser.add_argument(
            "--agent-configs",
            action="store_true",
            help="Scan agent configuration files for supply chain threats (~/.claude/settings.json, ~/.cursor/hooks.json, etc.)",
        )
        scan_parser.add_argument(
            "--sarif-output",
            metavar="FILE",
            help="Write SARIF format output to file (for CI/CD integration)",
        )
        scan_parser.add_argument(
            "--json-output", metavar="FILE", help="Write JSON format output to file"
        )
        scan_parser.add_argument(
            "--exit-code",
            action="store_true",
            help="Exit with code 1 if security issues found (for CI/CD)",
        )
        scan_parser.add_argument(
            "--verbose", "-v", action="store_true", help="Enable verbose output"
        )
        scan_parser.add_argument(
            "--diff",
            action="store_true",
            help="Scan only files changed between base branch and HEAD",
        )
        scan_parser.add_argument(
            "--base",
            metavar="REF",
            help="Base ref for --diff (default: auto-detect default branch)",
        )
        scan_parser.add_argument(
            "--staged",
            action="store_true",
            help="With --diff, scan only staged changes (git diff --cached)",
        )
        scan_parser.add_argument(
            "--pr",
            metavar="N_OR_URL",
            help="Scan files changed in GitHub PR (number or URL, requires gh CLI)",
        )
        scan_parser.add_argument(
            "--mr",
            metavar="N_OR_URL",
            help="Scan files changed in GitLab MR (number or URL, requires glab CLI)",
        )
        scan_parser.add_argument(
            "--stdin-diff",
            action="store_true",
            help="Read unified diff from stdin and scan changed files",
        )
        scan_parser.add_argument(
            "--changed-lines-only",
            action="store_true",
            help="Filter findings to only lines changed in the diff",
        )

        # Show-config subcommand (NEW in v1.5.0, DEPRECATED in v1.13.0)
        show_config_parser = subparsers.add_parser(
            "show-config",
            help="[DEPRECATED: use 'config show --summary'] Display effective configuration",
        )
        show_config_parser.add_argument(
            "--feature",
            choices=["ssrf", "secrets", "unicode", "config-scanner", "all"],
            default="all",
            help="Which feature to show (default: all)",
        )
        show_config_parser.add_argument(
            "--show-sources",
            action="store_true",
            help="Show source attribution (IMMUTABLE, SERVER, DEFAULT, LOCAL_CONFIG)",
        )
        show_config_parser.add_argument(
            "--json", action="store_true", help="Output as JSON"
        )
        show_config_parser.add_argument(
            "--config",
            metavar="FILE",
            help="Path to ai-guardian.json config file (default: auto-detect)",
        )

        # Config subcommand (NEW in v1.8.0, Issue #144)
        config_parser = subparsers.add_parser(
            "config",
            help="Configuration management (show merged config, preview auto-rules)",
        )
        config_sub = config_parser.add_subparsers(
            dest="config_command", help="Config commands"
        )

        # config show
        config_show_parser = config_sub.add_parser(
            "show", help="Display merged configuration"
        )
        config_show_parser.add_argument(
            "--all",
            action="store_true",
            help="Include auto-generated rules marked [GENERATED]",
        )
        config_show_parser.add_argument(
            "--section",
            metavar="NAME",
            help="Show specific section only (e.g., permissions, directory_rules)",
        )
        config_show_parser.add_argument(
            "--preview-auto-rules",
            action="store_true",
            help="Preview what auto-generation would create (without enabling)",
        )
        config_show_parser.add_argument(
            "--json", action="store_true", help="Output configuration as JSON"
        )
        config_show_parser.add_argument(
            "--summary",
            action="store_true",
            help="Display scanner feature summaries (SSRF, secrets, unicode, config-scanner)",
        )
        config_show_parser.add_argument(
            "--feature",
            choices=["ssrf", "secrets", "unicode", "config-scanner", "all"],
            default="all",
            help="Which feature to show with --summary (default: all)",
        )
        config_show_parser.add_argument(
            "--show-sources",
            action="store_true",
            help="Show source attribution with --summary (IMMUTABLE, SERVER, DEFAULT)",
        )
        config_show_parser.add_argument(
            "--config",
            metavar="FILE",
            help="Path to ai-guardian.json config file (default: auto-detect)",
        )

        # Scanner subcommand (NEW in v1.6.0)
        scanner_parser = subparsers.add_parser(
            "scanner", help="Manage scanner engines (install, list, info)"
        )
        scanner_sub = scanner_parser.add_subparsers(
            dest="scanner_command", help="Scanner commands"
        )

        # scanner list
        scanner_list_parser = scanner_sub.add_parser(
            "list", help="List installed scanners"
        )
        scanner_list_parser.add_argument(
            "--verbose", "-v", action="store_true", help="Show installation paths"
        )
        scanner_list_parser.add_argument(
            "--json", action="store_true", help="Output as JSON"
        )

        # scanner install
        scanner_install_parser = scanner_sub.add_parser(
            "install", help="Install a scanner"
        )
        scanner_install_parser.add_argument(
            "name",
            choices=[
                "gitleaks",
                "betterleaks",
                "leaktk",
                "trufflehog",
                "detect-secrets",
            ],
            help="Scanner to install",
        )
        scanner_install_parser.add_argument(
            "--version", help="Install specific version (e.g., 8.30.1)"
        )
        scanner_install_parser.add_argument(
            "--use-pinned",
            action="store_true",
            help="Use version from pyproject.toml (tested with this ai-guardian release)",
        )
        scanner_install_parser.add_argument(
            "--path",
            type=Path,
            help="Custom installation directory (default: /usr/local/bin, fallback: ~/.local/bin)",
        )

        # scanner info
        scanner_info_parser = scanner_sub.add_parser(
            "info", help="Show scanner details"
        )
        scanner_info_parser.add_argument(
            "name",
            choices=[
                "gitleaks",
                "betterleaks",
                "leaktk",
                "trufflehog",
                "detect-secrets",
            ],
            help="Scanner to show info for",
        )
        scanner_info_parser.add_argument(
            "--json", action="store_true", help="Output as JSON"
        )

        # scanner supported
        scanner_supported_parser = scanner_sub.add_parser(
            "supported", help="List all supported scanners with versions and repos"
        )
        scanner_supported_parser.add_argument(
            "--json", action="store_true", help="Output as JSON"
        )

        # ML model management subcommand (#185)
        ml_parser = subparsers.add_parser(
            "ml", help="Manage ML models for prompt injection detection"
        )
        ml_sub = ml_parser.add_subparsers(dest="ml_command", help="ML model commands")

        ml_setup_parser = ml_sub.add_parser(
            "setup",
            help="One-command ML detection setup (download model + configure)",
        )
        ml_setup_parser.add_argument(
            "--detector",
            choices=["hybrid", "ml"],
            default="hybrid",
            help="Detection mode: hybrid (heuristic+ML, recommended) or ml (ML only)",
        )
        ml_setup_parser.add_argument(
            "--model",
            default="protectai/deberta-v3-base-prompt-injection-v2",
            help="Model name from registry",
        )
        ml_setup_parser.add_argument(
            "--threshold",
            type=float,
            default=0.85,
            help="Confidence threshold (0.0-1.0, default: 0.85)",
        )
        ml_setup_parser.add_argument(
            "--force",
            action="store_true",
            help="Re-download model and overwrite existing config",
        )

        ml_download_parser = ml_sub.add_parser(
            "download", help="Download ML model from HuggingFace"
        )
        ml_download_parser.add_argument(
            "model",
            nargs="?",
            default="protectai/deberta-v3-base-prompt-injection-v2",
            help="Model name from registry (default: protectai/deberta-v3-base-prompt-injection-v2)",
        )
        ml_download_parser.add_argument(
            "--force",
            action="store_true",
            help="Re-download even if model already exists",
        )

        ml_sub.add_parser("list", help="List available and downloaded models")
        ml_sub.add_parser("status", help="Show ML detection status")

        ml_verify_parser = ml_sub.add_parser("verify", help="Verify ML model integrity")
        ml_verify_parser.add_argument(
            "model",
            nargs="?",
            default="protectai/deberta-v3-base-prompt-injection-v2",
            help="Model name to verify",
        )

        # Pattern-servers subcommand
        pattern_servers_parser = subparsers.add_parser(
            "pattern-servers", help="Pattern server management"
        )
        pattern_servers_sub = pattern_servers_parser.add_subparsers(
            dest="pattern_servers_command", help="Pattern server commands"
        )

        # pattern-servers supported
        ps_supported_parser = pattern_servers_sub.add_parser(
            "supported", help="List all supported pattern servers"
        )
        ps_supported_parser.add_argument(
            "--json", action="store_true", help="Output as JSON"
        )

        # Patterns subcommand (NEW in v1.9.0, Issue #337)
        patterns_parser = subparsers.add_parser(
            "patterns", help="List detection patterns across the system"
        )
        patterns_sub = patterns_parser.add_subparsers(
            dest="patterns_command", help="Pattern commands"
        )

        # patterns list
        patterns_list_parser = patterns_sub.add_parser(
            "list", help="List all detection pattern categories"
        )
        patterns_list_parser.add_argument(
            "--verbose",
            "-v",
            action="store_true",
            help="Show individual pattern breakdowns",
        )
        patterns_list_parser.add_argument(
            "--category",
            metavar="NAME",
            help="Filter by category name (e.g., prompt_injection, scan_pii, ssrf)",
        )
        patterns_list_parser.add_argument(
            "--json", action="store_true", help="Output as JSON"
        )

        # Sanitize subcommand (Issue #443)
        sanitize_parser = subparsers.add_parser(
            "sanitize", help="Redact secrets, PII, and threats from text"
        )
        sanitize_parser.add_argument(
            "input", nargs="?", help="File to sanitize (reads stdin if omitted)"
        )
        sanitize_parser.add_argument(
            "-o",
            "--output",
            help="Write output to file instead of stdout (required for image files)",
        )
        sanitize_parser.add_argument(
            "--no-secrets", action="store_true", help="Skip secret redaction"
        )
        sanitize_parser.add_argument(
            "--no-pii", action="store_true", help="Skip PII redaction"
        )
        sanitize_parser.add_argument(
            "--no-threats",
            action="store_true",
            help="Skip prompt injection and unicode attack neutralization",
        )
        sanitize_parser.add_argument(
            "--summary", action="store_true", help="Print redaction summary to stderr"
        )
        sanitize_parser.add_argument(
            "--exit-code",
            action="store_true",
            help="Exit with code 1 if redactions were made (for CI/CD)",
        )
        sanitize_parser.add_argument(
            "--output-dir",
            help="Output directory for sanitized files (required when input is a directory)",
        )
        sanitize_parser.add_argument(
            "--include",
            action="append",
            default=None,
            help="Glob pattern for files to include (repeatable; e.g., --include '*.py')",
        )
        sanitize_parser.add_argument(
            "--exclude",
            action="append",
            default=None,
            help="Glob pattern for files to exclude (repeatable; e.g., --exclude '*.log')",
        )
        sanitize_parser.add_argument(
            "--no-images",
            action="store_true",
            help="Skip image OCR processing (copy images as-is)",
        )
        sanitize_parser.add_argument(
            "--redact-strategy",
            choices=["blur", "blackout", "pixelate"],
            default="blackout",
            help="Image redaction method (default: blackout)",
        )
        sanitize_parser.add_argument(
            "--force",
            action="store_true",
            help="Allow writing to an existing output directory",
        )

        # Doctor subcommand (Issue #475)
        doctor_parser = subparsers.add_parser(
            "doctor", help="Check ai-guardian installation health"
        )
        doctor_parser.add_argument(
            "--json", action="store_true", help="Output results as JSON"
        )
        doctor_parser.add_argument(
            "--fix",
            action="store_true",
            help="Auto-fix issues that can be safely fixed",
        )
        doctor_parser.add_argument(
            "--quiet",
            action="store_true",
            help="Exit codes only (0=ok, 1=warnings, 2=errors)",
        )
        doctor_parser.add_argument(
            "--check-connectivity",
            action="store_true",
            help="Include network connectivity checks (pattern server)",
        )
        doctor_parser.add_argument(
            "--smoke-test",
            action="store_true",
            help="Run canary payload tests against each scanner to verify detection",
        )

        # Daemon subcommand
        daemon_parser = subparsers.add_parser(
            "daemon", help="Manage the background daemon service"
        )
        daemon_sub = daemon_parser.add_subparsers(
            dest="daemon_command", help="Daemon commands"
        )
        daemon_start_parser = daemon_sub.add_parser("start", help="Start daemon")
        daemon_start_parser.add_argument(
            "--background",
            "-b",
            action="store_true",
            help="Start daemon in background (detached)",
        )
        daemon_start_parser.add_argument(
            "--idle-timeout",
            type=int,
            default=None,
            help="Idle timeout in minutes (0 = disabled, default: 0)",
        )
        daemon_start_parser.add_argument(
            "--no-tray",
            action="store_true",
            help="Deprecated: daemon is always headless. Use 'ai-guardian tray' for system tray.",
        )
        daemon_sub.add_parser("stop", help="Stop running daemon")
        daemon_sub.add_parser("status", help="Show daemon status")
        daemon_sub.add_parser("restart", help="Restart daemon")
        daemon_sub.add_parser("reload", help="Force config reload without restart")
        daemon_sub.add_parser(
            "reset", help="Kill daemon and clean up state files for recovery"
        )

        # Per-directory pause/resume (#958)
        daemon_pause_parser = daemon_sub.add_parser(
            "pause", help="Pause scanning (global or per-directory)"
        )
        daemon_pause_parser.add_argument(
            "--dir",
            type=str,
            default=None,
            help="Project directory to pause (default: global pause)",
        )
        daemon_pause_parser.add_argument(
            "--minutes",
            type=int,
            default=0,
            help="Pause duration in minutes (default: indefinite)",
        )
        daemon_resume_parser = daemon_sub.add_parser(
            "resume", help="Resume scanning (global or per-directory)"
        )
        daemon_resume_parser.add_argument(
            "--dir",
            type=str,
            default=None,
            help="Project directory to resume (default: global resume)",
        )

        # Standalone tray subcommand (Issue #527)
        tray_parser = subparsers.add_parser(
            "tray", help="Manage standalone multi-daemon tray client"
        )
        tray_sub = tray_parser.add_subparsers(dest="tray_command", help="Tray commands")
        tray_start_parser = tray_sub.add_parser(
            "start", help="Start standalone tray (default)"
        )
        tray_start_parser.add_argument(
            "--background",
            "-b",
            action="store_true",
            help="Start tray in background (detached)",
        )
        tray_start_parser.add_argument(
            "--no-discover",
            action="store_true",
            help="Disable auto-discovery (manual targets only)",
        )
        tray_sub.add_parser("stop", help="Stop running standalone tray")
        tray_sub.add_parser("restart", help="Restart standalone tray")
        tray_parser.add_argument(
            "--install", action="store_true", help="Create desktop shortcut for tray"
        )
        tray_parser.add_argument(
            "--autostart",
            action="store_true",
            help="Enable launch on login (use with --install)",
        )
        tray_parser.add_argument(
            "--uninstall",
            action="store_true",
            help="Remove desktop shortcut and autostart",
        )

        # Unified prompt subcommand (Issue #1143, replaces tray-prompt and ask-prompt)
        prompt_parser = subparsers.add_parser(
            "prompt",
            help="Show interactive prompt dialog (parameter form or violation ask)",
        )
        prompt_parser.add_argument(
            "--mode",
            required=True,
            choices=["params", "ask"],
            help="Dialog mode: 'params' for tray plugin parameter form, 'ask' for violation decision",
        )
        prompt_parser.add_argument(
            "--output-file",
            default=None,
            help="Write result to this file instead of stdout",
        )
        # params mode arguments
        prompt_parser.add_argument(
            "--params",
            default=None,
            help="JSON array of parameter definitions (mode=params)",
        )
        prompt_parser.add_argument(
            "--template",
            default=None,
            help="Command template with {param} placeholders (mode=params)",
        )
        prompt_parser.add_argument(
            "--type",
            default="terminal",
            choices=["terminal", "background", "notification", "clipboard", "modal"],
            help="Command execution type (mode=params)",
        )
        prompt_parser.add_argument(
            "--extra-vars",
            default=None,
            help="JSON dict of extra variables for resolving param defaults (mode=params)",
        )
        prompt_parser.add_argument(
            "--title",
            default=None,
            help="Window title for the parameter form (mode=params)",
        )
        # ask mode arguments
        prompt_parser.add_argument(
            "--violation",
            default=None,
            help="JSON object with violation details (mode=ask)",
        )
        prompt_parser.add_argument(
            "--fallback",
            default="block",
            help="Fallback action when no dialog available (mode=ask, block/warn/log-only)",
        )
        prompt_parser.add_argument(
            "--timeout",
            default="300",
            help="Auto-dismiss timeout in seconds (mode=ask)",
        )

        # Tray target selector subcommand (Issue #760)
        tray_target_parser = subparsers.add_parser(
            "tray-target-select",
            help="Show multi-select target picker for tray plugin commands",
        )
        tray_target_parser.add_argument(
            "--targets",
            required=True,
            help="JSON array of target dicts (name, runtime, container_name, etc.)",
        )
        tray_target_parser.add_argument(
            "--output-file",
            default=None,
            help="Write selected target indices (JSON array) to this file",
        )

        # Dummy Agent subcommand (Issue #1438)
        dummy_agent_parser = subparsers.add_parser(
            "dummy-agent",
            help="Interactive fake IDE for hook testing without LLM",
        )
        dummy_agent_parser.add_argument(
            "--script",
            metavar="YAML",
            default=None,
            help="Run predefined scenarios from a YAML file (script mode)",
        )
        dummy_agent_parser.add_argument(
            "--no-color",
            action="store_true",
            help="Disable colored output",
        )

        # MCP server subcommand (Issue #477)
        subparsers.add_parser(
            "mcp-server", help="Start MCP security advisor server (stdio transport)"
        )

        # MCP security scanning subcommand (Issue #468)
        mcp_parser = subparsers.add_parser(
            "mcp",
            help="MCP server security: audit configs, scan source code, list servers",
        )
        mcp_sub = mcp_parser.add_subparsers(dest="mcp_command", help="MCP commands")

        mcp_list_parser = mcp_sub.add_parser(
            "list", help="List MCP servers with trust status"
        )
        mcp_list_parser.add_argument(
            "--verbose", "-v", action="store_true", help="Show env vars and args"
        )
        mcp_list_parser.add_argument(
            "--json", action="store_true", help="Output as JSON"
        )

        mcp_audit_parser = mcp_sub.add_parser(
            "audit", help="Audit MCP server configurations (fast)"
        )
        mcp_audit_parser.add_argument(
            "--json", action="store_true", help="Output as JSON"
        )
        mcp_audit_parser.add_argument(
            "--exit-code", action="store_true", help="Exit 1 if findings found"
        )

        mcp_scan_parser = mcp_sub.add_parser(
            "scan", help="Deep scan MCP server source code"
        )
        mcp_scan_parser.add_argument(
            "server", nargs="?", help="Server name to scan (default: all)"
        )
        mcp_scan_parser.add_argument(
            "--json", action="store_true", help="Output as JSON"
        )
        mcp_scan_parser.add_argument(
            "--exit-code", action="store_true", help="Exit 1 if findings found"
        )

        # Support bundle subcommand (Issue #511)
        support_parser = subparsers.add_parser(
            "support", help="Manage support bundles for troubleshooting"
        )
        support_sub = support_parser.add_subparsers(
            dest="support_command", help="Support commands"
        )

        # support prepare
        support_prepare_parser = support_sub.add_parser(
            "prepare", help="Prepare a sanitized support bundle for review"
        )
        support_prepare_parser.add_argument(
            "--output",
            "-o",
            metavar="PATH",
            help="Save bundle to this directory instead of a temp directory",
        )
        support_prepare_parser.add_argument(
            "--no-log",
            action="store_true",
            help="Exclude the ai-guardian.log file from the bundle",
        )
        support_prepare_parser.add_argument(
            "--no-violations",
            action="store_true",
            help="Exclude the violations.json file from the bundle",
        )
        support_prepare_parser.add_argument(
            "--json", action="store_true", help="Output bundle info as JSON"
        )

        # support send
        support_send_parser = support_sub.add_parser(
            "send", help="Send a prepared support bundle to the configured destination"
        )
        support_send_parser.add_argument(
            "--prepare",
            action="store_true",
            help="Prepare and send in one step (with confirmation unless --yes)",
        )
        support_send_parser.add_argument(
            "--yes", "-y", action="store_true", help="Skip confirmation prompt"
        )
        support_send_parser.add_argument(
            "--bundle",
            metavar="PATH",
            help="Path to a previously prepared bundle directory",
        )
        support_send_parser.add_argument(
            "--json", action="store_true", help="Output result as JSON"
        )

        # support status
        support_status_parser = support_sub.add_parser(
            "status", help="Show support bundle configuration and pending bundles"
        )
        support_status_parser.add_argument(
            "--json", action="store_true", help="Output as JSON"
        )

        # Trace export subcommand (Issue #1958)
        trace_parser = subparsers.add_parser(
            "trace", help="Trace export and management"
        )
        trace_sub = trace_parser.add_subparsers(
            dest="trace_command", help="Trace commands"
        )

        trace_export_parser = trace_sub.add_parser(
            "export", help="Export a trace file to OTLP format"
        )
        trace_export_parser.add_argument("file", help="Path to trace JSON file")
        trace_export_parser.add_argument(
            "--format",
            choices=["otlp-json", "otlp-proto"],
            default="otlp-json",
            help="Output format (default: otlp-json)",
        )
        trace_export_parser.add_argument(
            "--output", "-o", help="Output file path (default: stdout)"
        )
        trace_export_parser.add_argument(
            "--endpoint", help="OTLP collector endpoint URL (sends via HTTP POST)"
        )
        trace_export_parser.add_argument(
            "--service-name",
            default="ai-guardian-sdk",
            help="service.name resource attribute (default: ai-guardian-sdk)",
        )
        trace_export_parser.add_argument(
            "--header",
            action="append",
            dest="headers",
            metavar="KEY=VALUE",
            help="HTTP header for collector auth (repeatable, e.g., --header 'Authorization=Bearer tok')",
        )

        trace_export_dir_parser = trace_sub.add_parser(
            "export-dir", help="Export all traces in a directory to OTLP format"
        )
        trace_export_dir_parser.add_argument(
            "dir",
            nargs="?",
            help="Trace directory (default: SDK trace dir)",
        )
        trace_export_dir_parser.add_argument(
            "--format",
            choices=["otlp-json", "otlp-proto"],
            default="otlp-json",
            help="Output format (default: otlp-json)",
        )
        trace_export_dir_parser.add_argument("--output", "-o", help="Output directory")
        trace_export_dir_parser.add_argument(
            "--service-name",
            default="ai-guardian-sdk",
            help="service.name resource attribute (default: ai-guardian-sdk)",
        )

        # Engine test subcommand (Issue #542)
        engine_test_parser = subparsers.add_parser(
            "engine-test", help="Test strings against scanner engines"
        )
        engine_test_parser.add_argument(
            "--engine",
            choices=[
                "gitleaks",
                "betterleaks",
                "leaktk",
                "trufflehog",
                "detect-secrets",
                "secretlint",
                "gitguardian",
            ],
            help="Test against a specific engine",
        )
        engine_test_parser.add_argument(
            "--all",
            action="store_true",
            dest="all_engines",
            help="Test against all installed engines",
        )
        engine_test_parser.add_argument(
            "--compare",
            action="store_true",
            help="Show comparison table across all engines",
        )
        engine_test_parser.add_argument(
            "--pattern-server",
            action="store_true",
            help="Use pattern server configuration (if configured)",
        )
        engine_test_parser.add_argument(
            "--json", action="store_true", help="Output results as JSON"
        )

        # init-project subcommand (Issue #608)
        init_project_parser = subparsers.add_parser(
            "init-project",
            help="Scan project and generate security config (.ai-guardian/ and .aiguardignore.toml)",
        )
        init_project_parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be generated without writing files",
        )
        init_project_parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite existing .ai-guardian/ai-guardian.json (creates backup)",
        )
        init_project_parser.add_argument(
            "--merge",
            action="store_true",
            help="Deep-merge into existing config instead of skipping (creates backup)",
        )
        init_project_parser.add_argument(
            "--json", action="store_true", help="Output results as JSON"
        )
        init_project_parser.add_argument(
            "--dir",
            metavar="PATH",
            default=".",
            help="Project directory to scan (default: current directory)",
        )
        init_project_parser.add_argument(
            "--scan",
            action="store_true",
            help="Run full scan and auto-generate config from false-positive analysis",
        )
        init_project_parser.add_argument(
            "--threshold",
            type=int,
            default=10,
            metavar="N",
            help="Minimum file count to flag a pattern as false positive (default: 10)",
        )
        init_project_parser.add_argument(
            "--exact",
            action="store_true",
            help="Disable progressive suppression for exact finding counts (slower)",
        )
        init_project_parser.add_argument(
            "--exclude",
            action="append",
            default=[],
            metavar="PATTERN",
            help="Exclude glob pattern from scan (repeatable, e.g. --exclude 'data/*')",
        )

        args = parser.parse_args()

        # Auto-start daemon for CLI commands (Issue #680)
        _no_autostart = {"daemon", "mcp-server", "tray", "setup", "dummy-agent"}
        if args.command and args.command not in _no_autostart:
            _ensure_daemon_started()

        # Handle setup command
        if args.command == "setup":
            from ai_guardian.setup import setup_hooks

            install_scanner = args.install_scanner
            if install_scanner is not None and len(install_scanner) == 0:
                install_scanner = ["gitleaks"]
            success = setup_hooks(
                ide_type=args.ide,
                remote_config_url=args.remote_config_url,
                dry_run=args.dry_run,
                force=args.force,
                interactive=not args.yes,
                migrate_pattern_server=args.migrate_pattern_server,
                create_config=args.create_config,
                permissive=args.permissive,
                pre_commit=args.pre_commit,
                auto_install_hooks=args.auto_install_hooks,
                uninstall_hooks=args.uninstall_hooks,
                install_scanner=install_scanner,
                use_pinned=args.use_pinned,
                json_output=args.json_output,
                profile=args.profile,
                save_profile=args.save_profile,
                list_profiles=args.list_profiles,
                no_mcp=args.no_mcp or None,
                rules=args.rules if args.rules else None,
            )
            return 0 if success else 1

        # Handle violations command
        if args.command == "violations":
            if HAS_VIOLATION_LOGGER:
                return _handle_violations_command(args)
            else:
                print("Error: violation_logger module not available", file=sys.stderr)
                return 1

        # Handle metrics command (Issue #469)
        if args.command == "metrics":
            try:
                from ai_guardian.reporting.metrics import metrics_command

                return metrics_command(args)
            except ImportError as e:
                print(f"Error: Metrics module not available: {e}", file=sys.stderr)
                return 1
            except Exception as e:
                print(f"Error running metrics: {e}", file=sys.stderr)
                import traceback

                traceback.print_exc()
                return 1

        # Handle tui/console command
        if args.command in ("tui", "console"):
            if getattr(args, "web", False):
                try:
                    from ai_guardian.web import WebConsole, HAS_NICEGUI

                    if not HAS_NICEGUI:
                        print(
                            "Error: Web console requires NiceGUI (Python >= 3.10).",
                            file=sys.stderr,
                        )
                        return 1
                    console = WebConsole()
                    show = not getattr(args, "no_open", False)
                    console.run(port=getattr(args, "port", 0), show=show)
                    return 0
                except ImportError as e:
                    print(
                        f"Error: Web console dependencies not available: {e}",
                        file=sys.stderr,
                    )
                    print("Requires Python >= 3.10 with NiceGUI.", file=sys.stderr)
                    return 1
                except Exception as e:
                    print(f"Error running web console: {e}", file=sys.stderr)
                    return 1

            if not sys.stdin.isatty():
                print(
                    "Error: Console requires an interactive terminal.", file=sys.stderr
                )
                print(
                    "Run 'ai-guardian console' directly in your terminal.",
                    file=sys.stderr,
                )
                return 1
            try:
                from ai_guardian.tui import AIGuardianTUI

                app = AIGuardianTUI()
                initial_panel = getattr(args, "panel", None)
                if initial_panel:
                    app.initial_panel = initial_panel
                app.run()
                return 0
            except ImportError as e:
                print("Error: Console dependencies not available.", file=sys.stderr)
                print(f"Details: {e}", file=sys.stderr)
                return 1
            except Exception as e:
                print(f"Error running console: {e}", file=sys.stderr)
                return 1

        # Handle scan command
        if args.command == "scan":
            try:
                from ai_guardian.scanners.file_scanner import scan_command

                return scan_command(args)
            except ImportError as e:
                print(f"Error: Scanner module not available: {e}", file=sys.stderr)
                return 1
            except Exception as e:
                print(f"Error running scan: {e}", file=sys.stderr)
                import traceback

                traceback.print_exc()
                return 1

        # Handle show-config command (NEW in v1.5.0, DEPRECATED in v1.13.0)
        if args.command == "show-config":
            print(
                "WARNING: 'show-config' is deprecated. "
                "Use 'config show --summary' instead.",
                file=sys.stderr,
            )
            try:
                from ai_guardian.config.inspector import ConfigInspector

                # Load config
                if args.config:
                    config_path = Path(args.config)
                    if config_path.exists():
                        config = json.loads(config_path.read_text())
                    else:
                        print(
                            f"Error: Config file not found: {config_path}",
                            file=sys.stderr,
                        )
                        return 1
                else:
                    config, config_error = _load_config_file()
                    if config_error:
                        print(f"Warning: {config_error}", file=sys.stderr)
                    if config is None:
                        config = {}

                inspector = ConfigInspector(config)

                # Output format
                if args.json:
                    print(inspector.export_json())
                else:
                    # Display specific feature or all
                    if args.feature == "ssrf":
                        print(
                            inspector.show_ssrf_config(show_sources=args.show_sources)
                        )
                    elif args.feature == "secrets":
                        print(
                            inspector.show_secret_config(show_sources=args.show_sources)
                        )
                    elif args.feature == "unicode":
                        print(
                            inspector.show_unicode_config(
                                show_sources=args.show_sources
                            )
                        )
                    elif args.feature == "config-scanner":
                        print(
                            inspector.show_config_scanner_config(
                                show_sources=args.show_sources
                            )
                        )
                    else:  # all
                        print(inspector.show_all(show_sources=args.show_sources))

                return 0
            except ImportError as e:
                print(
                    f"Error: Config inspector module not available: {e}",
                    file=sys.stderr,
                )
                return 1
            except Exception as e:
                print(f"Error displaying configuration: {e}", file=sys.stderr)
                import traceback

                traceback.print_exc()
                return 1

        # Handle config command (NEW in v1.8.0, Issue #144)
        if args.command == "config":
            try:
                from ai_guardian.config.display import ConfigDisplay

                if args.config_command is None:
                    config_parser.print_help()
                    return 1

                if args.config_command == "show":
                    # Summary mode: scanner feature summaries (replaces show-config)
                    if getattr(args, "summary", False):
                        from ai_guardian.config.inspector import ConfigInspector

                        if getattr(args, "config", None):
                            config_path = Path(args.config)
                            if config_path.exists():
                                config = json.loads(config_path.read_text())
                            else:
                                print(
                                    f"Error: Config file not found: {config_path}",
                                    file=sys.stderr,
                                )
                                return 1
                        else:
                            config, config_error = _load_config_file()
                            if config_error:
                                print(f"Warning: {config_error}", file=sys.stderr)
                            if config is None:
                                config = {}

                        inspector = ConfigInspector(config)

                        if args.json:
                            print(inspector.export_json())
                        else:
                            feature = getattr(args, "feature", "all")
                            show_sources = getattr(args, "show_sources", False)
                            if feature == "ssrf":
                                print(
                                    inspector.show_ssrf_config(
                                        show_sources=show_sources
                                    )
                                )
                            elif feature == "secrets":
                                print(
                                    inspector.show_secret_config(
                                        show_sources=show_sources
                                    )
                                )
                            elif feature == "unicode":
                                print(
                                    inspector.show_unicode_config(
                                        show_sources=show_sources
                                    )
                                )
                            elif feature == "config-scanner":
                                print(
                                    inspector.show_config_scanner_config(
                                        show_sources=show_sources
                                    )
                                )
                            else:
                                print(inspector.show_all(show_sources=show_sources))
                        return 0

                    # Warn if summary-only flags used without --summary
                    if (
                        getattr(args, "show_sources", False)
                        or getattr(args, "feature", "all") != "all"
                    ):
                        print(
                            "Warning: --feature and --show-sources only apply "
                            "with --summary",
                            file=sys.stderr,
                        )

                    # Merged config display (default)
                    if getattr(args, "config", None):
                        config_path = Path(args.config)
                        if config_path.exists():
                            config = json.loads(config_path.read_text())
                            display = ConfigDisplay(config)
                        else:
                            print(
                                f"Error: Config file not found: {config_path}",
                                file=sys.stderr,
                            )
                            return 1
                    else:
                        display = ConfigDisplay()

                    output = display.show(
                        show_all=args.all,
                        section=args.section,
                        preview_auto_rules=args.preview_auto_rules,
                        output_json=args.json,
                    )
                    print(output)
                    return 0
                else:
                    print(
                        f"Unknown config command: {args.config_command}",
                        file=sys.stderr,
                    )
                    return 1

            except ImportError as e:
                print(
                    f"Error: Config display module not available: {e}", file=sys.stderr
                )
                return 1
            except Exception as e:
                print(f"Error displaying configuration: {e}", file=sys.stderr)
                import traceback

                traceback.print_exc()
                return 1

        # Handle scanner command (NEW in v1.6.0)
        if args.command == "scanner":
            try:
                from ai_guardian.scanners.installer import ScannerInstaller
                from ai_guardian.scanners.manager import ScannerManager

                if args.scanner_command == "list":
                    manager = ScannerManager()
                    if args.json:
                        print(manager.get_scanner_list_json())
                    else:
                        manager.print_scanner_list(verbose=args.verbose)
                    return 0

                elif args.scanner_command == "install":
                    # Create installer with custom path if provided
                    install_dir = (
                        args.path if hasattr(args, "path") and args.path else None
                    )
                    installer = ScannerInstaller(install_dir=install_dir)

                    print(f"Installing {args.name}...")
                    success = installer.install(
                        args.name, version=args.version, use_pinned=args.use_pinned
                    )

                    if success:
                        # Verify installation
                        if installer.verify_installation(args.name):
                            print(f"\n✓ {args.name} is ready to use")

                            # Show suggestion to update config
                            print(
                                f"\nRecommended: Update your configuration to use {args.name}"
                            )
                            from ai_guardian.config.utils import format_config_paths

                            print("\nAdd to your config:")
                            print(format_config_paths())
                            print("{")
                            print('  "secret_scanning": {')
                            print('    "enabled": true,')
                            print(f'    "engines": ["{args.name}"]')
                            print("  }")
                            print("}")
                        else:
                            print(
                                f"\n⚠ Installation completed but {args.name} verification failed"
                            )
                            print("Make sure ~/.local/bin is in your PATH")
                            return 1
                        return 0
                    else:
                        print(f"\n✗ Failed to install {args.name}")
                        return 1

                elif args.scanner_command == "info":
                    manager = ScannerManager()
                    if args.json:
                        print(manager.get_scanner_info_json(args.name))
                    else:
                        manager.print_scanner_info(args.name)
                    return 0

                elif args.scanner_command == "supported":
                    manager = ScannerManager()
                    if args.json:
                        print(manager.get_supported_scanners_json())
                    else:
                        manager.print_supported_scanners()
                    return 0

                else:
                    # No scanner subcommand provided
                    scanner_parser.print_help()
                    return 1

            except Exception as e:
                print(f"Error managing scanner: {e}", file=sys.stderr)
                import traceback

                traceback.print_exc()
                return 1

        # Handle ml command (#185)
        if args.command == "ml":
            return _handle_ml_command(args, ml_parser)

        # Handle pattern-servers command
        if args.command == "pattern-servers":
            try:
                from ai_guardian.scanners.manager import ScannerManager

                if args.pattern_servers_command is None:
                    pattern_servers_parser.print_help()
                    return 1

                if args.pattern_servers_command == "supported":
                    manager = ScannerManager()
                    if args.json:
                        print(manager.get_pattern_servers_json())
                    else:
                        manager.print_pattern_servers()
                    return 0

                else:
                    pattern_servers_parser.print_help()
                    return 1

            except Exception as e:
                print(f"Error managing pattern servers: {e}", file=sys.stderr)
                import traceback

                traceback.print_exc()
                return 1

        # Handle patterns command (NEW in v1.9.0, Issue #337)
        if args.command == "patterns":
            try:
                from ai_guardian.patterns.lister import PatternLister

                if args.patterns_command is None:
                    patterns_parser.print_help()
                    return 1

                if args.patterns_command == "list":
                    config, _ = _load_config_file()
                    lister = PatternLister(config=config)
                    if args.json:
                        print(lister.get_pattern_list_json(category=args.category))
                    else:
                        lister.print_pattern_list(
                            verbose=args.verbose, category=args.category
                        )
                    return 0

                else:
                    patterns_parser.print_help()
                    return 1

            except Exception as e:
                print(f"Error listing patterns: {e}", file=sys.stderr)
                import traceback

                traceback.print_exc()
                return 1

        # Handle sanitize command (Issue #443)
        if args.command == "sanitize":
            try:
                from ai_guardian.scanners.sanitizer import sanitize_command

                return sanitize_command(args)
            except ImportError as e:
                print(f"Error: Sanitizer module not available: {e}", file=sys.stderr)
                return 1
            except Exception as e:
                print(f"Error running sanitize: {e}", file=sys.stderr)
                import traceback

                traceback.print_exc()
                return 1

        # Handle doctor command (Issue #475)
        if args.command == "doctor":
            try:
                if getattr(args, "smoke_test", False):
                    from ai_guardian.smoke_test import smoke_test_command

                    return smoke_test_command(args)

                from ai_guardian.doctor import doctor_command

                return doctor_command(args)
            except ImportError as e:
                print(f"Error: Doctor module not available: {e}", file=sys.stderr)
                return 1
            except Exception as e:
                print(f"Error running doctor: {e}", file=sys.stderr)
                import traceback

                traceback.print_exc()
                return 1

        if args.command == "daemon":
            return _handle_daemon_command(args)

        # Handle tray command (Issue #527)
        if args.command == "tray":
            return _handle_tray_command(args)

        # Handle unified prompt command (Issue #1143)
        if args.command == "prompt":
            return _handle_prompt(args)

        # Handle tray-target-select command (Issue #760)
        if args.command == "tray-target-select":
            return _handle_tray_target_select(args)

        # Handle dummy-agent command (Issue #1438)
        if args.command == "dummy-agent":
            from ai_guardian.dummy_agent import run_interactive, run_script

            colors = not getattr(args, "no_color", False)
            if args.script:
                return run_script(args.script, colors=colors)
            run_interactive(colors=colors)
            return 0

        # Handle mcp-server command (Issue #477)
        if args.command == "mcp-server":
            try:
                from ai_guardian.mcp.server import run_mcp_server

                return run_mcp_server()
            except ImportError as e:
                print(
                    f"Error: MCP server not available. "
                    f"Requires Python >=3.10 and mcp package: {e}",
                    file=sys.stderr,
                )
                return 1

        # Handle mcp command (Issue #468)
        if args.command == "mcp":
            try:
                from ai_guardian.mcp.audit import MCPAuditor

                if not hasattr(args, "mcp_command") or args.mcp_command is None:
                    mcp_parser.print_help()
                    return 1

                auditor = MCPAuditor()
                servers = auditor.discover_servers()

                if args.mcp_command == "list":
                    if args.json:
                        print(auditor.get_server_list_json(servers))
                    else:
                        auditor.print_server_list(servers, verbose=args.verbose)
                    return 0

                elif args.mcp_command == "audit":
                    report = auditor.audit_config(servers)
                    if args.json:
                        print(auditor.get_audit_report_json(report))
                    else:
                        auditor.print_audit_report(report)
                    if args.exit_code and report.findings:
                        return 1
                    return 0

                elif args.mcp_command == "scan":
                    targets = servers
                    if args.server:
                        targets = [s for s in servers if s.name == args.server]
                        if not targets:
                            print(f"Server not found: {args.server}", file=sys.stderr)
                            print(
                                f"Available servers: {', '.join(s.name for s in servers)}",
                                file=sys.stderr,
                            )
                            return 1

                    all_reports = []
                    for server in targets:
                        report = auditor.scan_source(server)
                        if report:
                            all_reports.append(report)
                        else:
                            print(
                                f"Source not found for '{server.name}' (command: {server.command})"
                            )

                    if args.json:
                        json_data = [
                            json.loads(auditor.get_scan_report_json(r))
                            for r in all_reports
                        ]
                        print(json.dumps(json_data, indent=2))
                    else:
                        for report in all_reports:
                            auditor.print_scan_report(report)

                    if args.exit_code and any(r.findings for r in all_reports):
                        return 1
                    return 0

            except Exception as e:
                print(f"Error running MCP command: {e}", file=sys.stderr)
                import traceback

                traceback.print_exc()
                return 1

        # Handle support command (Issue #511)
        if args.command == "support":
            try:
                from ai_guardian.reporting.support_bundle import support_command

                return support_command(args)
            except ImportError as e:
                print(
                    f"Error: Support bundle module not available: {e}", file=sys.stderr
                )
                return 1
            except Exception as e:
                print(f"Error running support command: {e}", file=sys.stderr)
                import traceback

                traceback.print_exc()
                return 1

        # Handle init-project command (Issue #608)
        if args.command == "init-project":
            try:
                from ai_guardian.project_init import init_project_command

                return init_project_command(args)
            except ImportError as e:
                print(f"Error: Project init module not available: {e}", file=sys.stderr)
                return 1
            except Exception as e:
                print(f"Error running init-project: {e}", file=sys.stderr)
                import traceback

                traceback.print_exc()
                return 1

        # Handle trace command (Issue #1958)
        if args.command == "trace":
            try:
                from ai_guardian.scanners.otel_exporter import handle_trace_command

                return handle_trace_command(args, trace_parser)
            except ImportError as e:
                print(
                    f"Error: OTEL exporter module not available: {e}",
                    file=sys.stderr,
                )
                return 1
            except Exception as e:
                print(f"Error running trace command: {e}", file=sys.stderr)
                import traceback

                traceback.print_exc()
                return 1

        # Handle engine-test command (Issue #542)
        if args.command == "engine-test":
            try:
                from ai_guardian.scanners.engine_tester import engine_test_command

                return engine_test_command(args)
            except ImportError as e:
                print(
                    f"Error: Engine tester module not available: {e}", file=sys.stderr
                )
                return 1
            except Exception as e:
                print(f"Error running engine test: {e}", file=sys.stderr)
                import traceback

                traceback.print_exc()
                return 1

        # If --ide specified but no subcommand, set env var and fall through to hook mode
        if not args.command and getattr(args, "ide", None):
            os.environ["AI_GUARDIAN_IDE_TYPE"] = args.ide
        elif not args.command:
            # No subcommand, no --ide — version was already handled
            return 0

    # No arguments (or --ide only) - run as hook (read from stdin)
    # Load config once and share with both helpers
    _hook_config = None
    try:
        _hook_config, _ = _load_config_file()
    except Exception:
        pass  # intentionally silent — best-effort operation

    def _has_ask_action(config):
        """Check if any feature uses the ask action mode."""
        for section in (
            "secret_scanning",
            "prompt_injection",
            "scan_pii",
            "context_poisoning",
        ):
            sect = config.get(section, {})
            if isinstance(sect, dict):
                action = sect.get("action", "")
                if isinstance(action, str) and action.startswith("ask"):
                    return True
        rules = config.get("permissions", {}).get("rules", [])
        if isinstance(rules, list):
            for rule in rules:
                if isinstance(rule, dict):
                    action = rule.get("action", "")
                    if isinstance(action, str) and action.startswith("ask"):
                        return True
        return False

    hook_data = None
    response = None
    stdin_consumed = False

    try:
        from ai_guardian.daemon.client import (
            is_daemon_running,
            send_hook_request,
            start_daemon_background,
        )

        stdin_content = sys.stdin.read()
        stdin_consumed = True
        hook_data = json.loads(stdin_content)

        # Inject --ide override into hook_data so it survives daemon forwarding
        _cli_ide = os.environ.get("AI_GUARDIAN_IDE_TYPE")
        if _cli_ide and "_ide_type" not in hook_data:
            hook_data["_ide_type"] = _cli_ide

        running = is_daemon_running()
        if not running and not _is_stop_requested():
            logger.info("Daemon not running, starting...")
            running = start_daemon_background()

        if running:
            logger.info("Daemon is running, forwarding hook request")
            timeout = _get_client_timeout(config=_hook_config)
            if _hook_config and _has_ask_action(_hook_config):
                timeout = max(timeout, 310.0)
            response = send_hook_request(hook_data, timeout=timeout)
            if response is not None:
                logger.info("Daemon processed hook request")
            else:
                logger.warning("Daemon returned no response, falling back to direct")
        else:
            logger.info("Daemon unavailable, falling back to direct")
    except Exception as e:
        logger.info(f"Daemon client error, falling back to direct: {e}")

    if response is None:
        # Check persisted pause state before direct-mode fallback (#1319)
        from ai_guardian.daemon.state import DaemonState

        if DaemonState.is_paused_on_disk(cwd=os.getcwd()):
            logger.info("Scanning paused (persisted state), skipping direct fallback")
            response = {"output": "{}", "exit_code": 0}
        elif hook_data is not None:
            response = process_hook_data(hook_data)
        elif stdin_consumed:
            response = {"output": None, "exit_code": 0}
        else:
            response = process_hook_input()

    # Output JSON to stdout if needed (for Cursor)
    if response.get("output"):
        print(response["output"], flush=True)  # Force flush for Cursor
        sys.stdout.flush()  # Explicit flush for compatibility

    # Exit with appropriate code
    sys.exit(response["exit_code"])


if __name__ == "__main__":
    main()
