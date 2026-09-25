#!/usr/bin/env python3
"""
AI Guardian Doctor — health check command.

Verifies the entire ai-guardian setup is working correctly.
One command to diagnose all common issues.

Usage:
    ai-guardian doctor              # Human-readable output
    ai-guardian doctor --json       # Machine-readable JSON
    ai-guardian doctor --fix        # Auto-fix what can be fixed
    ai-guardian doctor --quiet      # Exit codes only (0=ok, 1=warnings, 2=errors)
"""

import difflib
import enum
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from ai_guardian.constants import CODEX_COVERAGE_NOTE
from ai_guardian.ide_registry import SUPPORTED_IDE_REGISTRY, get_ide_integration

logger = logging.getLogger(__name__)


class CheckStatus(enum.Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"


@dataclass
class CheckResult:
    name: str
    status: CheckStatus
    message: str
    detail: Optional[str] = None
    fix_hint: Optional[str] = None
    fixable: bool = False
    fixed: bool = False
    integrations: Optional[List[Dict[str, Any]]] = None


@dataclass
class DoctorReport:
    checks: List[CheckResult] = field(default_factory=list)
    version: str = ""

    @property
    def has_errors(self) -> bool:
        return any(c.status == CheckStatus.FAIL for c in self.checks)

    @property
    def has_warnings(self) -> bool:
        return any(c.status == CheckStatus.WARN for c in self.checks)

    @property
    def exit_code(self) -> int:
        if self.has_errors:
            return 2
        if self.has_warnings:
            return 1
        return 0


class Doctor:
    """Runs all health checks and produces a report."""

    def __init__(self, fix: bool = False, check_connectivity: bool = False):
        self.fix = fix
        self.check_connectivity = check_connectivity
        self._config: Optional[Dict] = None
        self._config_error: Optional[str] = None
        self._config_loaded = False

    def _ensure_config(self):
        if self._config_loaded:
            return
        self._config_loaded = True
        try:
            from ai_guardian import _load_config_file

            self._config, self._config_error = _load_config_file()
        except Exception as e:
            self._config_error = str(e)

    def run_all(self) -> DoctorReport:
        from ai_guardian import __version__

        self._ensure_config()
        report = DoctorReport(version=__version__)
        checks = [
            self.check_python_version,
            self.check_version_currency,
            self.check_config_file,
            self.check_project_config,
            self.check_config_overlay,
            self.check_deprecated_fields,
            self.check_unknown_config_keys,
            self.check_global_pattern_server,
            self.check_scanners,
            self.check_pattern_server,
            self.check_ps_cache_path,
            self.check_ps_auth,
            self.check_ps_url,
            self.check_ps_cache_freshness,
            self.check_hooks,
            self.check_state_dir,
            self.check_cache_dir,
            self.check_permissions,
            self.check_deprecated_action_on_allow,
            self.check_directory_rules,
            self.check_console_deps,
            self.check_tray_support,
            self.check_tkinter_support,
            self.check_ask_mode_deps,
            self.check_terminal_emulator,
            self.check_config_consistency,
            self.check_tighten_only,
            self.check_self_protection,
            self.check_image_scanning,
            self.check_tray_plugins,
            self.check_email_auth,
            self.check_ml_detection,
            self.check_ast_scanner,
            self.check_bandit_scanner,
            self.check_daemon_rest_port,
        ]
        for check_fn in checks:
            try:
                result = check_fn()
                report.checks.append(result)
            except Exception as e:
                fn_name = getattr(check_fn, "__name__", str(check_fn))
                report.checks.append(
                    CheckResult(
                        name=fn_name.replace("check_", ""),
                        status=CheckStatus.FAIL,
                        message=f"Check crashed: {e}",
                    )
                )
        return report

    def check_python_version(self) -> CheckResult:
        major, minor, micro = sys.version_info[:3]
        version_str = f"{major}.{minor}.{micro}"

        if (major, minor) < (3, 9):
            return CheckResult(
                name="python_version",
                status=CheckStatus.FAIL,
                message=f"Python {version_str} — unsupported (requires 3.9+)",
                fix_hint="Upgrade to Python 3.9+ (3.10+ recommended)",
            )

        if (major, minor) < (3, 10):
            return CheckResult(
                name="python_version",
                status=CheckStatus.WARN,
                message=f"Python {version_str} — AST-aware scanning disabled (requires 3.10+)",
                fix_hint="Upgrade to Python 3.10+ for reduced false positives on source code",
            )

        return CheckResult(
            name="python_version",
            status=CheckStatus.PASS,
            message=f"Python {version_str}",
        )

    def check_config_file(self) -> CheckResult:
        self._ensure_config()
        from ai_guardian.config.utils import get_config_dir

        config_dir = get_config_dir()
        config_path = config_dir / "ai-guardian.json"

        if not config_path.exists():
            local_path = Path.cwd() / ".ai-guardian.json"
            if local_path.exists():
                config_path = local_path
            else:
                return CheckResult(
                    name="config_file",
                    status=CheckStatus.WARN,
                    message="No config file found (using defaults)",
                    fix_hint="Run: ai-guardian setup --create-config",
                )

        if self._config_error:
            return CheckResult(
                name="config_file",
                status=CheckStatus.FAIL,
                message=f"Config error: {self._config_error}",
                fix_hint="Fix the JSON syntax in your config file",
            )

        # Schema validation
        schema_errors = self._validate_config_schema(self._config or {})
        if schema_errors:
            detail = "\n".join(f"  - {e}" for e in schema_errors[:5])
            return CheckResult(
                name="config_file",
                status=CheckStatus.WARN,
                message=f"Config has {len(schema_errors)} schema warning(s)",
                detail=detail,
            )

        path_display = str(config_path).replace(str(Path.home()), "~")
        return CheckResult(
            name="config_file",
            status=CheckStatus.PASS,
            message=f"Valid config at {path_display}",
        )

    def _validate_config_schema(self, config: Dict) -> List[str]:
        try:
            from jsonschema import Draft7Validator
        except ImportError:
            return []

        schema_path = (
            Path(__file__).parent / "schemas" / "ai-guardian-config.schema.json"
        )
        if not schema_path.exists():
            return []

        try:
            with open(schema_path) as f:
                schema = json.load(f)
            validator = Draft7Validator(schema)
            return [e.message for e in validator.iter_errors(config)]
        except Exception:
            return []

    def check_project_config(self) -> CheckResult:
        """Check if a project-level ai-guardian.json is detected."""
        try:
            from ai_guardian.config.utils import get_project_config_path

            project_path = get_project_config_path()
            if project_path:
                return CheckResult(
                    name="project_config",
                    status=CheckStatus.PASS,
                    message=f"Project config active: {project_path}",
                )
            return CheckResult(
                name="project_config",
                status=CheckStatus.PASS,
                message="No project config (using global only)",
            )
        except Exception as e:
            return CheckResult(
                name="project_config",
                status=CheckStatus.WARN,
                message=f"Error checking project config: {e}",
            )

    def check_config_overlay(self) -> CheckResult:
        """Check if an SDK config overlay is active."""
        import os
        from ai_guardian.config.loaders import _sdk_overlay

        sources = []

        overlay_file = os.environ.get("AI_GUARDIAN_CONFIG_OVERLAY")
        if overlay_file:
            p = Path(overlay_file).expanduser()
            if p.exists():
                sources.append(f"file: {overlay_file}")
            else:
                return CheckResult(
                    name="config_overlay",
                    status=CheckStatus.WARN,
                    message=f"AI_GUARDIAN_CONFIG_OVERLAY file not found: {overlay_file}",
                )

        inline = os.environ.get("AI_GUARDIAN_CONFIG_INLINE")
        if inline:
            sources.append("inline env var")

        if _sdk_overlay is not None:
            sources.append("configure() API")

        if not sources:
            return CheckResult(
                name="config_overlay",
                status=CheckStatus.PASS,
                message="No SDK overlay active",
            )

        return CheckResult(
            name="config_overlay",
            status=CheckStatus.PASS,
            message=f"SDK overlay active: {', '.join(sources)}",
        )

    def check_deprecated_fields(self) -> CheckResult:
        self._ensure_config()
        if self._config is None:
            return CheckResult(
                name="deprecated_fields",
                status=CheckStatus.PASS,
                message="No config loaded (nothing to check)",
            )

        schema_path = (
            Path(__file__).parent / "schemas" / "ai-guardian-config.schema.json"
        )
        deprecated_keys = []
        try:
            with open(schema_path) as f:
                schema = json.load(f)
            for key, prop_schema in schema.get("properties", {}).items():
                if prop_schema.get("deprecated"):
                    deprecated_keys.append(key)
        except Exception:
            pass  # intentionally silent — diagnostic check best-effort

        found = [k for k in deprecated_keys if k in self._config]
        if found:
            hints = {
                "pattern_server": "Run: ai-guardian setup --migrate-pattern-server",
                "directory_exclusions": "Migrate to 'directory_rules' format",
            }
            hint_parts = [hints.get(k, f"Remove '{k}'") for k in found]
            return CheckResult(
                name="deprecated_fields",
                status=CheckStatus.WARN,
                message=f"Deprecated field(s): {', '.join(found)}",
                fix_hint="; ".join(hint_parts),
            )

        return CheckResult(
            name="deprecated_fields",
            status=CheckStatus.PASS,
            message="No deprecated fields",
        )

    def check_unknown_config_keys(self) -> CheckResult:
        self._ensure_config()
        if self._config is None:
            return CheckResult(
                name="unknown_config_keys",
                status=CheckStatus.PASS,
                message="No config loaded (nothing to check)",
            )

        schema_path = (
            Path(__file__).parent / "schemas" / "ai-guardian-config.schema.json"
        )
        try:
            with open(schema_path) as f:
                schema = json.load(f)
        except Exception:
            return CheckResult(
                name="unknown_config_keys",
                status=CheckStatus.SKIP,
                message="Could not load config schema",
            )

        known_root_keys = set(schema.get("properties", {}).keys())
        known_root_keys.update(schema.get("definitions", {}).keys())

        try:
            from ai_guardian.setup.config import _get_default_config_template

            for k in _get_default_config_template():
                if not k.startswith("_") and not k.startswith("$"):
                    known_root_keys.add(k)
        except Exception:
            pass

        nested_known: Dict[str, set] = {}
        for key, prop_schema in schema.get("properties", {}).items():
            if isinstance(prop_schema, dict) and prop_schema.get("type") == "object":
                sub_props = prop_schema.get("properties", {})
                if sub_props:
                    nested_known[key] = set(sub_props.keys())
        for key, def_schema in schema.get("definitions", {}).items():
            if key not in nested_known and isinstance(def_schema, dict):
                sub_props = def_schema.get("properties", {})
                if sub_props:
                    nested_known[key] = set(sub_props.keys())

        warnings = []

        for key in self._config:
            if key.startswith("_") or key.startswith("$"):
                continue
            if key not in known_root_keys:
                matches = difflib.get_close_matches(
                    key, list(known_root_keys), n=1, cutoff=0.6
                )
                suggestion = f' — did you mean "{matches[0]}"?' if matches else ""
                warnings.append(f'Unknown config key "{key}"{suggestion}')

        for section_key, valid_sub_keys in nested_known.items():
            section = self._config.get(section_key)
            if not isinstance(section, dict):
                continue
            for sub_key in section:
                if sub_key.startswith("_") or sub_key.startswith("$"):
                    continue
                if sub_key not in valid_sub_keys:
                    matches = difflib.get_close_matches(
                        sub_key, list(valid_sub_keys), n=1, cutoff=0.6
                    )
                    suggestion = f' — did you mean "{matches[0]}"?' if matches else ""
                    warnings.append(
                        f'Unknown key "{sub_key}" in ' f'"{section_key}"{suggestion}'
                    )

        if warnings:
            return CheckResult(
                name="unknown_config_keys",
                status=CheckStatus.WARN,
                message=f"{len(warnings)} unknown config key(s) found",
                detail="\n".join(warnings),
                fix_hint="Check for typos in config key names",
            )

        return CheckResult(
            name="unknown_config_keys",
            status=CheckStatus.PASS,
            message="All config keys are recognized",
        )

    def check_global_pattern_server(self) -> CheckResult:
        """Check for deprecated global secret_scanning.pattern_server (Issue #530)."""
        self._ensure_config()
        if self._config is None:
            return CheckResult(
                name="global_pattern_server",
                status=CheckStatus.PASS,
                message="No config loaded",
            )

        ss = self._config.get("secret_scanning", {})
        if isinstance(ss, dict) and "pattern_server" in ss:
            ps = ss["pattern_server"]
            if ps is not None:
                if self.fix:
                    try:
                        from ai_guardian.setup import IDESetup

                        setup = IDESetup()
                        success, msg = setup.check_and_migrate_pattern_server(
                            dry_run=False, interactive=False
                        )
                        if success:
                            return CheckResult(
                                name="global_pattern_server",
                                status=CheckStatus.PASS,
                                message="Migrated to per-engine format",
                                fixable=True,
                                fixed=True,
                            )
                    except Exception as e:
                        return CheckResult(
                            name="global_pattern_server",
                            status=CheckStatus.WARN,
                            message=f"Migration failed: {e}",
                            fixable=True,
                        )

                return CheckResult(
                    name="global_pattern_server",
                    status=CheckStatus.WARN,
                    message="Deprecated: secret_scanning.pattern_server is global but only applies to gitleaks",
                    detail="Move to per-engine format: secret_scanning.engines[].pattern_server",
                    fix_hint="Run: ai-guardian doctor --fix  (or ai-guardian setup --migrate-pattern-server)",
                    fixable=True,
                )

        return CheckResult(
            name="global_pattern_server",
            status=CheckStatus.PASS,
            message="No global pattern_server (or using per-engine format)",
        )

    def check_scanners(self) -> CheckResult:
        try:
            from ai_guardian.scanners.manager import ScannerManager
        except ImportError:
            return CheckResult(
                name="scanners",
                status=CheckStatus.SKIP,
                message="Scanner manager not available",
            )

        manager = ScannerManager()
        installed = manager.list_installed()

        if not installed:
            return CheckResult(
                name="scanners",
                status=CheckStatus.FAIL,
                message="No scanners installed",
                fix_hint="Run: ai-guardian scanner install gitleaks",
            )

        names = [f"{s.name} {s.version}" for s in installed]
        unknown = [s for s in installed if s.version == "unknown"]
        if unknown:
            return CheckResult(
                name="scanners",
                status=CheckStatus.WARN,
                message=f"Installed: {', '.join(names)}",
                detail="Some scanners have unknown version",
            )

        return CheckResult(
            name="scanners",
            status=CheckStatus.PASS,
            message=", ".join(names),
        )

    def _get_ps_config(self) -> Optional[Dict]:
        """Extract pattern server config (per-engine, global, or root-level)."""
        self._ensure_config()
        if not self._config:
            return None
        ss = self._config.get("secret_scanning", {})
        if isinstance(ss, dict):
            # Priority 1: per-engine pattern_server
            for engine_spec in ss.get("engines", []):
                if isinstance(engine_spec, dict):
                    ps = engine_spec.get("pattern_server")
                    if isinstance(ps, dict) and ps.get("url"):
                        return ps
            # Priority 2: global secret_scanning.pattern_server (deprecated)
            if "pattern_server" in ss:
                ps = ss["pattern_server"]
                if isinstance(ps, dict) and ps.get("url"):
                    return ps
        # Priority 3: root-level pattern_server (deprecated)
        if "pattern_server" in self._config:
            ps = self._config["pattern_server"]
            if isinstance(ps, dict) and ps.get("url"):
                return ps
        return None

    def _refresh_ps_cache(self, ps_config: Dict) -> tuple:
        """Attempt to refresh pattern cache. Returns (success, error_msg)."""
        try:
            from ai_guardian.patterns.server import PatternServerClient

            client = PatternServerClient(ps_config)
            result = client.get_patterns_path()
            if result and result.exists():
                return True, None
            return False, "Fetch returned no path"
        except Exception as e:
            return False, str(e)

    def check_pattern_server(self) -> CheckResult:
        ps_config = self._get_ps_config()
        if not ps_config:
            return CheckResult(
                name="pattern_server",
                status=CheckStatus.SKIP,
                message="No pattern server configured",
            )
        return CheckResult(
            name="pattern_server",
            status=CheckStatus.PASS,
            message="Configured",
            detail=f"URL: {ps_config.get('url', 'unknown')}",
        )

    def check_ps_cache_path(self) -> CheckResult:
        ps_config = self._get_ps_config()
        if not ps_config:
            return CheckResult(
                name="ps_cache_path",
                status=CheckStatus.SKIP,
                message="No pattern server configured",
            )

        cache_config = ps_config.get("cache", {})
        is_custom_path = bool(
            cache_config.get("path")
            or os.environ.get("AI_GUARDIAN_CACHE_DIR")
            or os.environ.get("XDG_CACHE_HOME")
        )
        if cache_config.get("path"):
            cache_dir = Path(cache_config["path"]).expanduser().parent
        else:
            from ai_guardian.config.utils import get_cache_dir

            cache_dir = get_cache_dir()

        if not cache_dir.exists():
            if is_custom_path:
                return CheckResult(
                    name="ps_cache_path",
                    status=CheckStatus.FAIL,
                    message=f"{_tilde(cache_dir)} — does not exist",
                    fix_hint="Run: ai-guardian doctor --fix  (or set cache.path / XDG_CACHE_HOME)",
                    fixable=True,
                )
            return CheckResult(
                name="ps_cache_path",
                status=CheckStatus.WARN,
                message=f"{_tilde(cache_dir)} — not yet created (will be created on first hook call)",
            )

        if not os.access(cache_dir, os.W_OK):
            return CheckResult(
                name="ps_cache_path",
                status=CheckStatus.FAIL,
                message=f"{_tilde(cache_dir)} — not writable",
                fix_hint="Set cache.path to a writable location or set XDG_CACHE_HOME",
            )

        return CheckResult(
            name="ps_cache_path",
            status=CheckStatus.PASS,
            message=f"{_tilde(cache_dir)} (writable)",
        )

    def check_ps_auth(self) -> CheckResult:
        ps_config = self._get_ps_config()
        if not ps_config:
            return CheckResult(
                name="ps_auth",
                status=CheckStatus.SKIP,
                message="No pattern server configured",
            )

        auth_config = ps_config.get("auth", {})
        if not auth_config:
            return CheckResult(
                name="ps_auth",
                status=CheckStatus.SKIP,
                message="No auth configured (public server)",
            )

        token_env = auth_config.get("token_env", "AI_GUARDIAN_PATTERN_TOKEN")
        token_file = Path(
            auth_config.get("token_file", "~/.config/ai-guardian/pattern-token")
        ).expanduser()

        if os.environ.get(token_env):
            return CheckResult(
                name="ps_auth",
                status=CheckStatus.PASS,
                message=f"Token found in ${token_env}",
            )

        if token_file.exists():
            try:
                content = token_file.read_text().strip()
                if content:
                    return CheckResult(
                        name="ps_auth",
                        status=CheckStatus.PASS,
                        message=f"Token found in {_tilde(token_file)}",
                    )
            except Exception:
                pass  # intentionally silent — diagnostic check best-effort

        return CheckResult(
            name="ps_auth",
            status=CheckStatus.FAIL,
            message="Token not set",
            fix_hint=f"export {token_env}=your-token",
        )

    def check_ps_url(self) -> CheckResult:
        ps_config = self._get_ps_config()
        if not ps_config:
            return CheckResult(
                name="ps_url",
                status=CheckStatus.SKIP,
                message="No pattern server configured",
            )

        if not self.check_connectivity:
            return CheckResult(
                name="ps_url",
                status=CheckStatus.SKIP,
                message="Skipped (use --check-connectivity)",
            )

        url = ps_config.get("url", "").rstrip("/")
        endpoint = ps_config.get("patterns_endpoint", "/patterns/gitleaks/8.18.1")
        full_url = f"{url}{endpoint}"

        if full_url.startswith("http://"):
            return CheckResult(
                name="ps_url",
                status=CheckStatus.FAIL,
                message="HTTP not allowed (use HTTPS)",
                fix_hint="Change pattern server URL to https://",
            )

        try:
            import requests as req
        except ImportError:
            return CheckResult(
                name="ps_url",
                status=CheckStatus.FAIL,
                message="requests library not available",
            )

        headers = {"User-Agent": "ai-guardian/doctor"}
        auth_config = ps_config.get("auth", {})
        token_env = auth_config.get("token_env", "AI_GUARDIAN_PATTERN_TOKEN")
        token = os.environ.get(token_env)
        if not token:
            token_file = Path(
                auth_config.get("token_file", "~/.config/ai-guardian/pattern-token")
            ).expanduser()
            if token_file.exists():
                try:
                    token = token_file.read_text().strip()
                except Exception:
                    pass  # intentionally silent — diagnostic check best-effort
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            resp = req.get(full_url, headers=headers, timeout=10, verify=True)
        except req.exceptions.Timeout:
            return CheckResult(
                name="ps_url",
                status=CheckStatus.WARN,
                message=f"Timeout ({url})",
                fix_hint="Using cached patterns if available",
            )
        except req.exceptions.ConnectionError:
            return CheckResult(
                name="ps_url",
                status=CheckStatus.FAIL,
                message=f"Connection failed ({url})",
            )
        except Exception as e:
            return CheckResult(
                name="ps_url",
                status=CheckStatus.FAIL,
                message=f"Error: {e}",
            )

        if resp.status_code == 401:
            return CheckResult(
                name="ps_url",
                status=CheckStatus.FAIL,
                message="401 Unauthorized",
                fix_hint=f"export {token_env}=your-token",
            )
        if resp.status_code != 200:
            return CheckResult(
                name="ps_url",
                status=CheckStatus.FAIL,
                message=f"{resp.status_code} from {url}",
            )

        rule_count = self._count_toml_rules(resp.text)
        msg = f"{url} (200 OK"
        if rule_count is not None:
            msg += f", {rule_count} rules"
        msg += ")"

        return CheckResult(
            name="ps_url",
            status=CheckStatus.PASS,
            message=msg,
        )

    def _count_toml_rules(self, text: str) -> Optional[int]:
        """Count rules in a TOML response (best effort)."""
        try:
            if sys.version_info >= (3, 11):
                import tomllib
            else:
                import tomli as tomllib  # type: ignore
            data = tomllib.loads(text)
            rules = data.get("rules", [])
            if isinstance(rules, list):
                return len(rules)
        except Exception:
            pass  # intentionally silent — diagnostic check best-effort
        return None

    def check_ps_cache_freshness(self) -> CheckResult:
        ps_config = self._get_ps_config()
        if not ps_config:
            return CheckResult(
                name="ps_cache_freshness",
                status=CheckStatus.SKIP,
                message="No pattern server configured",
            )

        cache_config = ps_config.get("cache", {})
        if cache_config.get("path"):
            cache_file = Path(cache_config["path"]).expanduser()
        else:
            from ai_guardian.config.utils import get_cache_dir

            cache_file = get_cache_dir() / "patterns.toml"

        if not cache_file.exists():
            if self.fix:
                ok, err = self._refresh_ps_cache(ps_config)
                if ok:
                    return CheckResult(
                        name="ps_cache_freshness",
                        status=CheckStatus.PASS,
                        message="Fetched patterns from server",
                        fixable=True,
                        fixed=True,
                    )
                return CheckResult(
                    name="ps_cache_freshness",
                    status=CheckStatus.WARN,
                    message="No cached patterns",
                    fix_hint=(
                        f"Fetch failed: {err}"
                        if err
                        else "Fetch failed — check URL and auth settings"
                    ),
                    fixable=True,
                )
            return CheckResult(
                name="ps_cache_freshness",
                status=CheckStatus.PASS,
                message="No cached patterns yet (fetched on first scan)",
            )

        age_seconds = time.time() - cache_file.stat().st_mtime
        age_days = age_seconds / 86400

        expire_hours = cache_config.get("expire_after_hours", 168)
        expire_days = expire_hours / 24

        rule_count = None
        try:
            content = cache_file.read_text()
            rule_count = self._count_toml_rules(content)
        except Exception:
            pass  # intentionally silent — diagnostic check best-effort

        age_str = f"{int(age_days)} days old" if age_days >= 1 else "< 1 day old"
        rule_str = f", {rule_count} rules" if rule_count is not None else ""

        if age_days > expire_days:
            if self.fix:
                ok, err = self._refresh_ps_cache(ps_config)
                if ok:
                    return CheckResult(
                        name="ps_cache_freshness",
                        status=CheckStatus.PASS,
                        message="Refreshed expired patterns from server",
                        fixable=True,
                        fixed=True,
                    )
                return CheckResult(
                    name="ps_cache_freshness",
                    status=CheckStatus.FAIL,
                    message=f"Expired ({age_str}{rule_str})",
                    fix_hint=(
                        f"Refresh failed: {err}"
                        if err
                        else "Refresh failed — check URL and auth settings"
                    ),
                    fixable=True,
                )
            return CheckResult(
                name="ps_cache_freshness",
                status=CheckStatus.FAIL,
                message=f"Expired ({age_str}{rule_str})",
                fix_hint="Run: ai-guardian doctor --fix",
                fixable=True,
            )

        refresh_hours = cache_config.get("refresh_interval_hours", 12)
        refresh_days = refresh_hours / 24

        if age_days > refresh_days:
            if self.fix:
                ok, err = self._refresh_ps_cache(ps_config)
                if ok:
                    return CheckResult(
                        name="ps_cache_freshness",
                        status=CheckStatus.PASS,
                        message="Refreshed stale patterns from server",
                        fixable=True,
                        fixed=True,
                    )
                return CheckResult(
                    name="ps_cache_freshness",
                    status=CheckStatus.WARN,
                    message=f"Stale ({age_str}{rule_str})",
                    fix_hint=(
                        f"Refresh failed: {err}"
                        if err
                        else "Refresh failed — check URL and auth settings"
                    ),
                    fixable=True,
                )
            return CheckResult(
                name="ps_cache_freshness",
                status=CheckStatus.WARN,
                message=f"Stale ({age_str}{rule_str})",
                fix_hint="Run: ai-guardian doctor --fix",
                fixable=True,
            )

        return CheckResult(
            name="ps_cache_freshness",
            status=CheckStatus.PASS,
            message=f"{cache_file.name} ({age_str}{rule_str})",
        )

    def check_hooks(self) -> CheckResult:
        try:
            from ai_guardian.setup import IDESetup
        except ImportError:
            return CheckResult(
                name="hooks",
                status=CheckStatus.SKIP,
                message="Setup module not available",
            )

        setup = IDESetup()
        detected = set(setup.list_detected_ides())
        results = []
        integration_results = []
        all_configured = True
        any_configured = False
        any_installed = False

        for integration in SUPPORTED_IDE_REGISTRY:
            ide_type = integration.key
            ide_name = integration.display_name
            raw_config_path = setup.get_config_path(ide_type)
            cursor_layers = []
            if ide_type == "cursor" and ide_type in detected:
                cursor_layers = setup.get_cursor_config_layers()

            installed = ide_type in detected and (
                raw_config_path is None
                or self._has_ide_install_evidence(
                    setup, ide_type, raw_config_path, cursor_layers
                )
            )
            if not installed:
                results.append(f"{ide_name}: not installed")
                integration_results.append(
                    {
                        "ide": ide_type,
                        "name": ide_name,
                        "display_name": ide_name,
                        "status": CheckStatus.SKIP.value,
                        "message": "Not installed",
                        "installed": False,
                    }
                )
                continue

            any_installed = True
            if raw_config_path is None:
                message = "Configuration path unavailable"
                results.append(f"{ide_name}: {message}")
                integration_results.append(
                    {
                        "ide": ide_type,
                        "name": ide_name,
                        "display_name": ide_name,
                        "status": CheckStatus.FAIL.value,
                        "message": message,
                        "installed": True,
                    }
                )
                all_configured = False
                continue

            config_path = Path(raw_config_path).expanduser()

            if ide_type == "codex":
                verification = setup.verify_ide_setup(ide_type)
                events = verification.get("events", {})
                hook_count = sum(status == "healthy" for status in events.values())
                total = len(setup.expected_hook_manifest("codex"))
                mcp_status = verification.get("mcp_status", "missing")
                message = (
                    f"{hook_count}/{total} hooks; MCP: {mcp_status}; "
                    f"{CODEX_COVERAGE_NOTE}"
                )
                results.append(f"{ide_name}: {message}")
                detail = self._hook_verification_detail(verification)
                integration_results.append(
                    {
                        "ide": ide_type,
                        "name": ide_name,
                        "display_name": ide_name,
                        "status": (
                            CheckStatus.PASS.value
                            if verification.get("healthy") is True
                            and hook_count >= total
                            else CheckStatus.WARN.value
                        ),
                        "message": message,
                        "detail": detail,
                        "installed": True,
                        "verification": verification,
                    }
                )
                any_configured = True
                if verification.get("healthy") is not True or hook_count < total:
                    all_configured = False
                continue

            if ide_type == "cursor":
                verification = setup.verify_ide_setup(ide_type)
                events = verification.get("events", {})
                hook_count = sum(status == "healthy" for status in events.values())
                total = len(setup.expected_hook_manifest("cursor"))
                effective_events = verification.get("effective_events", {})
                effective_hook_count = (
                    sum(status == "healthy" for status in effective_events.values())
                    if isinstance(effective_events, dict)
                    else hook_count
                )
                installation_scope = verification.get("installation_scope", "user")
                effective_scope = verification.get("effective_scope", "none")
                mcp_status = verification.get("mcp_status", "missing")
                effective_mcp_status = verification.get(
                    "effective_mcp_status", mcp_status
                )
                scope_detail = installation_scope
                if effective_scope != installation_scope:
                    scope_detail += f"; effective: {effective_scope}"
                hook_detail = f"{hook_count}/{total} hooks"
                if effective_hook_count != hook_count:
                    hook_detail += f"; effective: {effective_hook_count}/{total}"
                mcp_detail = f"MCP: {mcp_status}"
                if effective_mcp_status != mcp_status:
                    mcp_detail += f"; effective: {effective_mcp_status}"
                message = f"{hook_detail} (scope: {scope_detail}); {mcp_detail}"
                results.append(f"{ide_name}: {message}")
                detail = self._hook_verification_detail(verification)
                integration_results.append(
                    {
                        "ide": ide_type,
                        "name": ide_name,
                        "display_name": ide_name,
                        "status": (
                            CheckStatus.PASS.value
                            if verification.get("healthy") is True
                            and hook_count >= total
                            else CheckStatus.WARN.value
                        ),
                        "message": message,
                        "detail": detail,
                        "installed": True,
                        "verification": verification,
                    }
                )
                any_configured = True
                if verification.get("healthy") is not True or hook_count < total:
                    all_configured = False
                continue

            configured, detail = setup.check_hooks_for_ide(ide_type)
            mcp_verification = None
            mcp_status = None
            mcp_integration = get_ide_integration(ide_type)
            if (
                ide_type not in ("codex", "cursor")
                and mcp_integration is not None
                and mcp_integration.supports_mcp
            ):
                from ai_guardian.setup.mcp import verify_mcp_config

                mcp_verification = verify_mcp_config(ide_type)
                mcp_status = mcp_verification.get("mcp_status")
            mcp_detail = f"; MCP: {mcp_status}" if mcp_status else ""
            mcp_healthy = mcp_status in (None, "healthy", "external")

            if configured:
                if ide_type == "claude":
                    hook_count = self._count_claude_hooks(config_path)
                    total = len(setup.expected_hook_manifest("claude"))
                    message = f"{hook_count}/{total} hooks{mcp_detail}"
                    item_status = (
                        CheckStatus.PASS if hook_count >= total else CheckStatus.WARN
                    )
                    if not mcp_healthy:
                        item_status = CheckStatus.WARN
                    results.append(f"{ide_name}: {message}")
                    integration_results.append(
                        {
                            "ide": ide_type,
                            "name": ide_name,
                            "display_name": ide_name,
                            "status": item_status.value,
                            "message": message,
                            "installed": True,
                        }
                    )
                    if mcp_verification is not None:
                        integration_results[-1]["verification"] = mcp_verification
                    if hook_count < total or not mcp_healthy:
                        all_configured = False
                elif ide_type == "codex":
                    hook_count = self._count_codex_hooks(config_path)
                    total = len(setup.expected_hook_manifest("codex"))
                    message = f"{hook_count}/{total} hooks"
                    results.append(f"{ide_name}: {message}")
                    integration_results.append(
                        {
                            "ide": ide_type,
                            "name": ide_name,
                            "display_name": ide_name,
                            "status": (
                                CheckStatus.PASS.value
                                if hook_count >= total
                                else CheckStatus.WARN.value
                            ),
                            "message": message,
                            "installed": True,
                        }
                    )
                    if hook_count < total:
                        all_configured = False
                else:
                    message = (
                        self._hook_detail_without_name(detail, ide_name) + mcp_detail
                    )
                    results.append(f"{ide_name}: {message}")
                    integration_results.append(
                        {
                            "ide": ide_type,
                            "name": ide_name,
                            "display_name": ide_name,
                            "status": (
                                CheckStatus.PASS.value
                                if mcp_healthy
                                else CheckStatus.WARN.value
                            ),
                            "message": message,
                            "installed": True,
                        }
                    )
                    if mcp_verification is not None:
                        integration_results[-1]["verification"] = mcp_verification
                    if not mcp_healthy:
                        all_configured = False
                any_configured = True
            else:
                message = self._hook_detail_without_name(detail, ide_name) + mcp_detail
                item_status = (
                    CheckStatus.WARN
                    if "needs attention" in detail
                    else CheckStatus.FAIL
                )
                results.append(f"{ide_name}: {message}")
                integration_results.append(
                    {
                        "ide": ide_type,
                        "name": ide_name,
                        "display_name": ide_name,
                        "status": item_status.value,
                        "message": message,
                        "installed": True,
                    }
                )
                if mcp_verification is not None:
                    integration_results[-1]["verification"] = mcp_verification
                if "needs attention" in detail:
                    any_configured = True
                all_configured = False

        detail_str = "; ".join(results)

        if not any_installed:
            return CheckResult(
                name="hooks",
                status=CheckStatus.WARN,
                message="No IDEs detected" if not detected else detail_str,
                fix_hint="Install a supported IDE or CLI integration",
                integrations=integration_results,
            )
        if all_configured:
            return CheckResult(
                name="hooks",
                status=CheckStatus.PASS,
                message=detail_str,
                integrations=integration_results,
            )
        elif any_configured:
            return CheckResult(
                name="hooks",
                status=CheckStatus.WARN,
                message=detail_str,
                fix_hint="Run: ai-guardian setup",
                integrations=integration_results,
            )
        else:
            return CheckResult(
                name="hooks",
                status=CheckStatus.FAIL,
                message=detail_str,
                fix_hint="Run: ai-guardian setup",
                integrations=integration_results,
            )

    @staticmethod
    def _has_ide_install_evidence(
        setup, ide_type: str, raw_config_path: str, cursor_layers: List[Dict]
    ) -> bool:
        """Return whether a detected integration has local installation evidence."""
        if ide_type == "cursor":
            return any(
                layer.get("exists")
                or (
                    layer.get("path")
                    and Path(layer["path"]).expanduser().parent.is_dir()
                )
                for layer in cursor_layers
            )

        config_path = Path(raw_config_path).expanduser()
        if config_path.exists():
            return True

        ide_config = setup.IDE_CONFIGS.get(ide_type, {})
        executable = ide_config.get("executable")
        if executable:
            return shutil.which(executable) is not None

        # Crush is project-local and its file is the installation evidence;
        # treating the repository root as evidence would mark every project as
        # an installed Crush integration.
        if ide_type == "crush":
            return False

        return config_path.parent != Path(".") and config_path.parent.is_dir()

    @staticmethod
    def _hook_detail_without_name(detail: str, ide_name: str) -> str:
        prefix = f"{ide_name}: "
        return detail[len(prefix) :] if detail.startswith(prefix) else detail

    @staticmethod
    def _hook_verification_detail(verification: Dict[str, Any]) -> Optional[str]:
        """Return concise attention details for an installed hook integration."""
        attention = [
            name
            for name, status in verification.get("events", {}).items()
            if status != "healthy"
        ]
        attention.extend(
            f"obsolete:{name}" for name in verification.get("obsolete", [])
        )
        attention.extend(str(item) for item in verification.get("diagnostics", []))
        return ", ".join(attention) or None

    def _count_claude_hooks(self, config_path: Path) -> int:
        from ai_guardian.setup import IDESetup

        return self._count_nested_hooks(
            config_path, IDESetup().expected_hook_manifest("claude")
        )

    def _count_codex_hooks(self, config_path: Path) -> int:
        from ai_guardian.setup import IDESetup

        return self._count_nested_hooks(
            config_path, IDESetup().expected_hook_manifest("codex")
        )

    @staticmethod
    def _count_nested_hooks(config_path: Path, event_names) -> int:
        from ai_guardian.setup import _is_ai_guardian_command

        try:
            with open(config_path) as f:
                config = json.load(f)
            hooks = config.get("hooks", {})
            count = 0
            for hook_name in event_names:
                if hook_name in hooks:
                    hook_list = hooks[hook_name]
                    if isinstance(hook_list, list):
                        for entry in hook_list:
                            if isinstance(entry, dict) and "hooks" in entry:
                                for h in entry["hooks"]:
                                    if isinstance(h, dict) and _is_ai_guardian_command(
                                        h.get("command", "")
                                    ):
                                        count += 1
                                        break
            return count
        except Exception:
            return 0

    def _count_cursor_hooks(self, config_path: Path) -> int:
        from ai_guardian.setup import _is_ai_guardian_command
        from ai_guardian.setup import IDESetup

        try:
            with open(config_path) as f:
                config = json.load(f)
            hooks = config.get("hooks", {})
            count = 0
            for hook_name in IDESetup().expected_hook_manifest("cursor"):
                if hook_name in hooks:
                    hook_list = hooks[hook_name]
                    if isinstance(hook_list, list):
                        for entry in hook_list:
                            if isinstance(entry, dict) and _is_ai_guardian_command(
                                entry.get("command", "")
                            ):
                                count += 1
                                break
            return count
        except Exception:
            return 0

    def check_state_dir(self) -> CheckResult:
        from ai_guardian.config.utils import get_state_dir, get_config_dir

        state_dir = get_state_dir()
        config_dir = get_config_dir()

        if not state_dir.exists():
            if self.fix:
                try:
                    state_dir.mkdir(parents=True, exist_ok=True)
                    return CheckResult(
                        name="state_dir",
                        status=CheckStatus.PASS,
                        message=f"Created {_tilde(state_dir)}",
                        fixable=True,
                        fixed=True,
                    )
                except OSError as e:
                    return CheckResult(
                        name="state_dir",
                        status=CheckStatus.FAIL,
                        message=f"Cannot create: {e}",
                        fixable=True,
                    )
            return CheckResult(
                name="state_dir",
                status=CheckStatus.WARN,
                message=f"Missing: {_tilde(state_dir)}",
                fix_hint="Run: ai-guardian doctor --fix",
                fixable=True,
            )

        if not os.access(state_dir, os.W_OK):
            return CheckResult(
                name="state_dir",
                status=CheckStatus.FAIL,
                message=f"Not writable: {_tilde(state_dir)}",
            )

        # Check for old location files
        if config_dir != state_dir:
            old_files = [
                f
                for f in ["violations.jsonl", "ai-guardian.log"]
                if (config_dir / f).exists()
            ]
            if old_files:
                if self.fix:
                    from ai_guardian.config.utils import migrate_state_files

                    migrate_state_files()
                    # Remove old files after successful migration
                    removed = []
                    for f in old_files:
                        old_path = config_dir / f
                        new_path = state_dir / f
                        if new_path.exists() and old_path.exists():
                            try:
                                old_path.unlink()
                                removed.append(f)
                            except OSError:
                                pass  # intentionally silent — cleanup best-effort
                    return CheckResult(
                        name="state_dir",
                        status=CheckStatus.PASS,
                        message=f"OK ({_tilde(state_dir)}), migrated old files",
                        fixable=True,
                        fixed=True,
                    )
                return CheckResult(
                    name="state_dir",
                    status=CheckStatus.WARN,
                    message=f"Old files in config dir: {', '.join(old_files)}",
                    fix_hint="Run: ai-guardian doctor --fix",
                    fixable=True,
                )

        # Count violations
        violations_file = state_dir / "violations.jsonl"
        detail = None
        if violations_file.exists():
            try:
                count = sum(1 for _ in open(violations_file))
                detail = f"{count} violations logged"
            except Exception:
                pass  # intentionally silent — diagnostic check best-effort

        return CheckResult(
            name="state_dir",
            status=CheckStatus.PASS,
            message=f"OK ({_tilde(state_dir)})",
            detail=detail,
        )

    def check_cache_dir(self) -> CheckResult:
        from ai_guardian.config.utils import get_cache_dir

        cache_dir = get_cache_dir()

        if not cache_dir.exists():
            try:
                cache_dir.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                return CheckResult(
                    name="cache_dir",
                    status=CheckStatus.FAIL,
                    message=f"Cannot create: {e}",
                )

        if not os.access(cache_dir, os.W_OK):
            return CheckResult(
                name="cache_dir",
                status=CheckStatus.FAIL,
                message=f"Not writable: {_tilde(cache_dir)}",
            )

        # Check pattern cache freshness
        patterns_file = cache_dir / "patterns.toml"
        if patterns_file.exists():
            age_days = (time.time() - patterns_file.stat().st_mtime) / 86400
            if age_days > 7:
                return CheckResult(
                    name="cache_dir",
                    status=CheckStatus.WARN,
                    message=f"Pattern cache stale ({int(age_days)}d old)",
                )
            return CheckResult(
                name="cache_dir",
                status=CheckStatus.PASS,
                message=f"OK, patterns fresh ({int(age_days)}d old)",
            )

        return CheckResult(
            name="cache_dir",
            status=CheckStatus.PASS,
            message=f"OK ({_tilde(cache_dir)})",
        )

    def check_permissions(self) -> CheckResult:
        self._ensure_config()
        if self._config is None:
            return CheckResult(
                name="permissions",
                status=CheckStatus.WARN,
                message="No config loaded",
            )

        perms = self._config.get("permissions")
        if not isinstance(perms, dict):
            return CheckResult(
                name="permissions",
                status=CheckStatus.WARN,
                message="No permissions section configured",
            )

        rules = perms.get("rules", [])
        if not isinstance(rules, list) or len(rules) == 0:
            return CheckResult(
                name="permissions",
                status=CheckStatus.WARN,
                message="No permission rules defined",
            )

        # Validate rule structure
        invalid = []
        for i, rule in enumerate(rules):
            if not isinstance(rule, dict):
                invalid.append(f"Rule {i}: not a dict")
                continue
            if "matcher" not in rule:
                invalid.append(f"Rule {i}: missing 'matcher'")

        if invalid:
            return CheckResult(
                name="permissions",
                status=CheckStatus.FAIL,
                message=f"{len(invalid)} invalid rule(s)",
                detail="\n".join(f"  - {e}" for e in invalid[:5]),
            )

        return CheckResult(
            name="permissions",
            status=CheckStatus.PASS,
            message=f"{len(rules)} rule(s) configured",
        )

    def check_deprecated_action_on_allow(self) -> CheckResult:
        self._ensure_config()
        if self._config is None:
            return CheckResult(
                name="deprecated_action_on_allow",
                status=CheckStatus.PASS,
                message="No config loaded (nothing to check)",
            )

        perms = self._config.get("permissions")
        if not isinstance(perms, dict):
            return CheckResult(
                name="deprecated_action_on_allow",
                status=CheckStatus.PASS,
                message="No permissions section",
            )

        rules = perms.get("rules", [])
        deprecated = []
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            if rule.get("mode") == "allow" and rule.get("action"):
                matcher = rule.get("matcher", "?")
                action = rule.get("action")
                deprecated.append(
                    f'"action": "{action}" on allow rule (matcher={matcher})'
                )

        if deprecated:
            return CheckResult(
                name="deprecated_action_on_allow",
                status=CheckStatus.WARN,
                message=f"Deprecated: {deprecated[0]}",
                detail=(
                    "\n".join(f"  - {d}" for d in deprecated)
                    if len(deprecated) > 1
                    else None
                ),
                fix_hint='Remove "action" or split into separate deny + allow rules',
            )

        return CheckResult(
            name="deprecated_action_on_allow",
            status=CheckStatus.PASS,
            message="No deprecated action on allow rules",
        )

    def check_directory_rules(self) -> CheckResult:
        self._ensure_config()
        if self._config is None:
            return CheckResult(
                name="directory_rules",
                status=CheckStatus.WARN,
                message="No config loaded",
            )

        dir_rules = self._config.get("directory_rules")

        # Handle both array and object formats
        rules_list = []
        if isinstance(dir_rules, list):
            rules_list = dir_rules
        elif isinstance(dir_rules, dict):
            rules_list = dir_rules.get("rules", [])

        if not rules_list:
            return CheckResult(
                name="directory_rules",
                status=CheckStatus.PASS,
                message="No directory rules configured (using defaults)",
            )

        # Validate structure — rules can use "pattern", "paths", or "path"
        invalid = []
        user_count = 0
        generated_count = 0
        for i, rule in enumerate(rules_list):
            if not isinstance(rule, dict):
                invalid.append(f"Rule {i}: not a dict")
                continue
            has_target = any(k in rule for k in ("pattern", "paths", "path"))
            if not has_target:
                invalid.append(f"Rule {i}: missing 'pattern' or 'paths'")
            if rule.get("_generated"):
                generated_count += 1
            else:
                user_count += 1

        if invalid:
            return CheckResult(
                name="directory_rules",
                status=CheckStatus.FAIL,
                message=f"{len(invalid)} invalid rule(s)",
                detail="\n".join(f"  - {e}" for e in invalid[:5]),
            )

        return CheckResult(
            name="directory_rules",
            status=CheckStatus.PASS,
            message=f"{user_count} user, {generated_count} generated rule(s)",
        )

    def check_console_deps(self) -> CheckResult:
        missing = []

        try:
            import textual  # noqa: F401
        except ImportError:
            missing.append("textual")

        try:
            import tree_sitter  # noqa: F401
        except ImportError:
            missing.append("tree-sitter")

        try:
            import tree_sitter_json  # noqa: F401
        except ImportError:
            missing.append("tree-sitter-json")

        if missing:
            ts_missing = [m for m in missing if m.startswith("tree-sitter")]
            if ts_missing and sys.version_info < (3, 10):
                hint = "AST scanning requires Python >= 3.10"
            else:
                hint = f"Not available: {', '.join(missing)}"
            return CheckResult(
                name="console_deps",
                status=CheckStatus.WARN,
                message=hint,
            )

        return CheckResult(
            name="console_deps",
            status=CheckStatus.PASS,
            message="All console dependencies installed",
        )

    def check_config_consistency(self) -> CheckResult:
        schema_path = (
            Path(__file__).parent / "schemas" / "ai-guardian-config.schema.json"
        )
        if not schema_path.exists():
            return CheckResult(
                name="config_consistency",
                status=CheckStatus.SKIP,
                message="Schema file not found",
            )

        try:
            with open(schema_path) as f:
                schema = json.load(f)
        except Exception:
            return CheckResult(
                name="config_consistency",
                status=CheckStatus.SKIP,
                message="Cannot load schema",
            )

        # Check that all properties with defaults are consistent
        mismatches = []
        props = schema.get("properties", {})
        for key, prop_schema in props.items():
            if "default" in prop_schema and "type" in prop_schema:
                default_val = prop_schema["default"]
                expected_type = prop_schema["type"]
                type_map: Dict[str, Union[type, Tuple[type, ...]]] = {
                    "boolean": bool,
                    "string": str,
                    "integer": int,
                    "number": (int, float),
                    "object": dict,
                    "array": list,
                }
                py_type = type_map.get(expected_type)
                if py_type and not isinstance(default_val, py_type):
                    mismatches.append(f"{key}: default type mismatch")

        if mismatches:
            return CheckResult(
                name="config_consistency",
                status=CheckStatus.WARN,
                message=f"{len(mismatches)} mismatch(es)",
                detail="\n".join(f"  - {m}" for m in mismatches),
            )

        return CheckResult(
            name="config_consistency",
            status=CheckStatus.PASS,
            message="Schema defaults consistent",
        )

    def check_tray_support(self) -> CheckResult:
        """Check if system tray icon can be displayed on this platform."""
        system = platform.system()

        if system in ("Windows", "Darwin"):
            try:
                import pystray  # noqa: F401

                label = "Windows" if system == "Windows" else "macOS"
                return CheckResult(
                    name="tray_support",
                    status=CheckStatus.PASS,
                    message=f"pystray available ({label})",
                )
            except ImportError:
                return CheckResult(
                    name="tray_support",
                    status=CheckStatus.WARN,
                    message="pystray not available — tray icon unavailable",
                )

        if system != "Linux":
            return CheckResult(
                name="tray_support",
                status=CheckStatus.SKIP,
                message=f"Unsupported platform ({system})",
            )

        # Linux: check GObject Introspection (gi) availability
        try:
            import gi  # noqa: F401
        except ImportError:
            return CheckResult(
                name="tray_support",
                status=CheckStatus.WARN,
                message=(
                    "GObject Introspection (gi) not available — "
                    "tray requires it on Linux"
                ),
                fix_hint=(
                    "Install the system package:\n"
                    "  Fedora/RHEL: sudo dnf install python3-gobject\n"
                    "  Debian/Ubuntu: sudo apt install python3-gi\n"
                    "  openSUSE: sudo zypper install python3-gobject\n"
                    "  Arch: sudo pacman -S python-gobject\n"
                    "Or install PyGObject: pip install PyGObject\n"
                    "  (headers may be needed first:\n"
                    "  Fedora/RHEL: sudo dnf install gobject-introspection-devel "
                    "cairo-gobject-devel pkg-config python3-devel gcc\n"
                    "  Debian/Ubuntu: sudo apt install libgirepository1.0-dev "
                    "gcc libcairo2-dev pkg-config python3-dev)"
                ),
            )

        # Linux: check GNOME AppIndicator
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
        if "GNOME" not in desktop.upper():
            return CheckResult(
                name="tray_support",
                status=CheckStatus.SKIP,
                message=f"Not GNOME ({desktop or 'unknown'})",
            )

        if not shutil.which("gnome-extensions"):
            return CheckResult(
                name="tray_support",
                status=CheckStatus.SKIP,
                message="gnome-extensions command not found",
            )

        try:
            result = subprocess.run(
                ["gnome-extensions", "list", "--enabled"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if "appindicatorsupport@rgcjonas.gmail.com" in result.stdout:
                return CheckResult(
                    name="tray_support",
                    status=CheckStatus.PASS,
                    message="AppIndicator extension enabled",
                )
        except (subprocess.TimeoutExpired, OSError):
            return CheckResult(
                name="tray_support",
                status=CheckStatus.SKIP,
                message="Could not query GNOME extensions",
            )

        return CheckResult(
            name="tray_support",
            status=CheckStatus.WARN,
            message="GNOME detected — AppIndicator extension required for tray icon",
            fix_hint=(
                "sudo dnf install gnome-shell-extension-appindicator.noarch && "
                "log out/in, then: gnome-extensions enable "
                "appindicatorsupport@rgcjonas.gmail.com"
            ),
        )

    def check_tkinter_support(self) -> CheckResult:
        """Check if tkinter is available for native tray plugin popups."""
        if os.environ.get("AI_GUARDIAN_NO_TKINTER"):
            return CheckResult(
                name="tkinter_support",
                status=CheckStatus.SKIP,
                message="Disabled via AI_GUARDIAN_NO_TKINTER",
            )

        try:
            import tkinter  # noqa: F401
        except ImportError:
            try:
                import nicegui  # noqa: F401

                return CheckResult(
                    name="tkinter_support",
                    status=CheckStatus.PASS,
                    message="tkinter unavailable — NiceGUI fallback active",
                )
            except ImportError:
                return CheckResult(
                    name="tkinter_support",
                    status=CheckStatus.WARN,
                    message="tkinter unavailable — popups use Textual terminal fallback",
                    fix_hint=(
                        "Install tkinter for native popups: "
                        "brew install tcl-tk (macOS/pyenv), "
                        "dnf install python3-tkinter (RHEL), "
                        "apt install python3-tk (Debian)"
                    ),
                )

        try:
            import nicegui  # noqa: F401

            fallback = "NiceGUI"
        except ImportError:
            fallback = "Textual"

        return CheckResult(
            name="tkinter_support",
            status=CheckStatus.PASS,
            message=f"tkinter available (fallback: {fallback})",
        )

    def check_ask_mode_deps(self) -> CheckResult:
        """Check that ask mode has a usable dialog backend (tkinter or NiceGUI)."""
        self._ensure_config()
        if not self._config:
            return CheckResult(
                name="ask_mode_deps",
                status=CheckStatus.SKIP,
                message="No config loaded",
            )

        ask_sections = []
        for section in (
            "scan_pii",
            "prompt_injection",
            "context_poisoning",
            "supply_chain",
            "config_file_scanning",
        ):
            action = (self._config.get(section) or {}).get("action", "")
            if isinstance(action, str) and action.startswith("ask"):
                ask_sections.append(section)

        for rule in (self._config.get("permissions") or {}).get("rules", []):
            action = rule.get("action", "")
            if isinstance(action, str) and action.startswith("ask"):
                ask_sections.append("permissions.rules")
                break

        for rule in (self._config.get("directory_rules") or {}).get("rules", []):
            action = rule.get("action", "")
            if isinstance(action, str) and action.startswith("ask"):
                ask_sections.append("directory_rules.rules")
                break

        if not ask_sections:
            return CheckResult(
                name="ask_mode_deps",
                status=CheckStatus.SKIP,
                message="No ask actions configured",
            )

        has_tkinter = False
        try:
            import tkinter  # noqa: F401

            has_tkinter = True
        except ImportError:
            pass  # intentionally silent — optional dependency

        if has_tkinter:
            return CheckResult(
                name="ask_mode_deps",
                status=CheckStatus.PASS,
                message=f"tkinter available for ask mode ({', '.join(ask_sections)})",
            )

        has_nicegui = False
        try:
            import nicegui  # noqa: F401

            has_nicegui = True
        except ImportError:
            pass  # intentionally silent — optional dependency

        if has_nicegui:
            return CheckResult(
                name="ask_mode_deps",
                status=CheckStatus.PASS,
                message=f"NiceGUI fallback for ask mode ({', '.join(ask_sections)})",
            )

        return CheckResult(
            name="ask_mode_deps",
            status=CheckStatus.WARN,
            message=(
                f"Ask mode configured ({', '.join(ask_sections)}) "
                "but tkinter/NiceGUI unavailable — Textual terminal fallback only"
            ),
            fix_hint=(
                "Install tkinter for native ask dialogs:\n"
                "  Fedora/RHEL: sudo dnf install python3-tkinter\n"
                "  Debian/Ubuntu: sudo apt install python3-tk\n"
                "  macOS (pyenv): brew install tcl-tk\n"
                "Or install NiceGUI: pip install nicegui"
            ),
        )

    def check_terminal_emulator(self) -> CheckResult:
        """Check if a supported terminal emulator is installed (Linux only)."""
        if platform.system() != "Linux":
            return CheckResult(
                name="terminal_emulator",
                status=CheckStatus.SKIP,
                message="Not Linux",
            )

        supported = [
            "gnome-terminal",
            "kgx",
            "konsole",
            "xfce4-terminal",
            "xterm",
        ]
        found = [t for t in supported if shutil.which(t)]

        if found:
            return CheckResult(
                name="terminal_emulator",
                status=CheckStatus.PASS,
                message=f"{found[0]} found",
            )

        return CheckResult(
            name="terminal_emulator",
            status=CheckStatus.WARN,
            message="No supported terminal found — tray Console won't work",
            fix_hint="sudo dnf install gnome-terminal   # or: sudo apt install gnome-terminal",
        )

    def check_tighten_only(self) -> CheckResult:
        """Report sections with tighten-only immutable policy."""
        self._ensure_config()
        if self._config is None:
            return CheckResult(
                name="tighten_only",
                status=CheckStatus.PASS,
                message="No config loaded",
            )

        tighten_sections = []
        for key, value in self._config.items():
            if isinstance(value, dict) and value.get("immutable") == "tighten-only":
                tighten_sections.append(key)

        if not tighten_sections:
            return CheckResult(
                name="tighten_only",
                status=CheckStatus.PASS,
                message="No tighten-only policies",
            )

        return CheckResult(
            name="tighten_only",
            status=CheckStatus.WARN,
            message=f"Tighten-only policy: {', '.join(tighten_sections)}",
            detail="Lower-level configs can tighten but not loosen these sections",
        )

    def check_self_protection(self) -> CheckResult:
        """Verify immutable patterns protect config/state/cache from agent access."""
        from ai_guardian.tools.patterns import IMMUTABLE_DENY_PATTERNS

        issues = []

        read_patterns = IMMUTABLE_DENY_PATTERNS.get("Read", [])
        if not read_patterns:
            issues.append("No Read patterns defined")
        else:
            for required in [
                "*/.config/ai-guardian/*",
                "*/.local/state/ai-guardian/*",
                "*/.cache/ai-guardian/*",
            ]:
                if required not in read_patterns:
                    issues.append(f"Missing Read pattern: {required}")

        bash_patterns = IMMUTABLE_DENY_PATTERNS.get("Bash", [])
        for required in [
            "*cat*/.config/ai-guardian/*",
            "*cat*/.local/state/ai-guardian/*",
        ]:
            if required not in bash_patterns:
                issues.append(f"Missing Bash pattern: {required}")

        for required in [
            "*ai-guardian*pause*",
            "*ai-guardian*resume*",
            "*ai-guardian*stop*",
            "*ai-guardian*disable*",
            "*ai-guardian*uninstall*",
        ]:
            if required not in bash_patterns:
                issues.append(f"Missing Bash CLI pattern: {required}")

        if issues:
            return CheckResult(
                name="self_protection",
                status=CheckStatus.FAIL,
                message=f"{len(issues)} gap(s) in agent protection",
                detail="\n".join(f"  - {i}" for i in issues),
            )

        return CheckResult(
            name="self_protection",
            status=CheckStatus.PASS,
            message="Config, state, cache, CLI read-protected from agent",
        )

    def check_image_scanning(self) -> CheckResult:
        """Check OCR engine availability when image scanning is enabled."""
        self._ensure_config()
        img_config = (self._config or {}).get("image_scanning", {})
        if not img_config.get("enabled", True):
            return CheckResult(
                name="image_scanning",
                status=CheckStatus.SKIP,
                message="Image scanning not enabled",
            )

        missing = []
        try:
            from rapidocr import RapidOCR  # noqa: F401
        except ImportError:
            missing.append("rapidocr")

        try:
            import onnxruntime  # noqa: F401
        except ImportError:
            missing.append("onnxruntime")

        if missing:
            return CheckResult(
                name="image_scanning",
                status=CheckStatus.FAIL,
                message=(
                    f"{', '.join(missing)} not available "
                    "(required for image scanning)"
                ),
            )

        return CheckResult(
            name="image_scanning",
            status=CheckStatus.PASS,
            message="rapidocr and onnxruntime available for image OCR scanning",
        )

    def check_ml_detection(self) -> CheckResult:
        """Check ML prompt injection model availability."""
        self._ensure_config()
        pi_config = (self._config or {}).get("prompt_injection", {})
        detector = pi_config.get("detector", "heuristic")

        if detector not in ("ml", "hybrid"):
            return CheckResult(
                name="ml_detection",
                status=CheckStatus.SKIP,
                message=f"ML detection not configured (detector='{detector}')",
            )

        try:
            from ai_guardian.scanners.ml_detection import is_ml_available, verify_model
        except ImportError:
            return CheckResult(
                name="ml_detection",
                status=CheckStatus.FAIL,
                message="ML detection module not found",
            )

        if not is_ml_available():
            return CheckResult(
                name="ml_detection",
                status=CheckStatus.FAIL,
                message="ML dependencies not available (onnxruntime required)",
            )

        engines_config = pi_config.get("ml_engines", [])
        if not engines_config:
            from ai_guardian.config.utils import get_config_dir

            return CheckResult(
                name="ml_detection",
                status=CheckStatus.WARN,
                message="detector is 'ml'/'hybrid' but no ml_engines configured",
                fix_hint=(
                    "Add ml_engines to prompt_injection config in "
                    f"{get_config_dir() / 'ai-guardian.json'}"
                ),
            )

        errors = []
        for eng in engines_config:
            model = eng.get("model", "")
            if model:
                is_valid, msg = verify_model(model)
                if not is_valid:
                    errors.append(f"{model}: {msg}")

        if errors:
            return CheckResult(
                name="ml_detection",
                status=CheckStatus.FAIL,
                message=f"ML model issues: {'; '.join(errors)}",
                fix_hint="ai-guardian ml download",
            )

        return CheckResult(
            name="ml_detection",
            status=CheckStatus.PASS,
            message=f"ML detection ready ({len(engines_config)} engine(s), strategy={pi_config.get('ml_strategy', 'any-match')})",
        )

    def check_tray_plugins(self) -> CheckResult:
        """Check tray plugin files for validity and circular imports."""
        from ai_guardian.daemon import get_tray_plugins_dir
        from ai_guardian.tray.plugins import check_circular_imports

        plugins_dir = get_tray_plugins_dir()
        if not plugins_dir.is_dir():
            return CheckResult(
                name="tray_plugins",
                status=CheckStatus.SKIP,
                message="No tray-plugins directory",
            )

        json_files = list(plugins_dir.glob("*.json"))
        if not json_files:
            return CheckResult(
                name="tray_plugins",
                status=CheckStatus.SKIP,
                message="No plugin files",
            )

        circular = check_circular_imports(plugins_dir)
        if circular:
            chains = "; ".join(circular)
            return CheckResult(
                name="tray_plugins",
                status=CheckStatus.WARN,
                message=f"Circular import: {chains}",
            )

        return CheckResult(
            name="tray_plugins",
            status=CheckStatus.PASS,
            message=f"{len(json_files)} plugin file(s) OK",
        )

    def check_ast_scanner(self) -> CheckResult:
        """Check if tree-sitter AST scanner is available and list language parsers."""
        try:
            import tree_sitter
        except ImportError:
            return CheckResult(
                name="ast_scanner",
                status=CheckStatus.WARN,
                message="tree-sitter not installed — code files scanned as raw text (higher FP rate)",
                fix_hint="pip install tree-sitter",
            )

        try:
            from importlib.metadata import version as pkg_version

            version = pkg_version("tree-sitter")
        except Exception:
            version = getattr(tree_sitter, "__version__", "unknown")

        from ai_guardian.scanners.ast_scanner import _GRAMMAR_IMPORTS

        available = []
        for lang_name, module_name in sorted(_GRAMMAR_IMPORTS.items()):
            try:
                import importlib

                importlib.import_module(module_name)
                available.append(lang_name.capitalize())
            except ImportError:
                pass  # intentionally silent — optional dependency

        if not available:
            return CheckResult(
                name="ast_scanner",
                status=CheckStatus.WARN,
                message=f"tree-sitter {version} installed but no language parsers found",
                fix_hint="pip install tree-sitter-python tree-sitter-javascript ...",
            )

        langs = ", ".join(available)
        return CheckResult(
            name="ast_scanner",
            status=CheckStatus.PASS,
            message=f"tree-sitter {version} ({langs})",
        )

    def check_bandit_scanner(self) -> CheckResult:
        """Check availability of the configured code-security inspectors."""
        import importlib.util

        self._ensure_config()
        code_cfg = (self._config or {}).get("code_scanning", {})

        try:
            from ai_guardian.config.utils import is_feature_enabled

            code_enabled = is_feature_enabled(code_cfg.get("enabled"), default=True)
        except Exception:
            code_enabled = code_cfg.get("enabled", True)

        if not code_enabled:
            return CheckResult(
                name="bandit_scanner",
                status=CheckStatus.SKIP,
                message="Code scanning disabled in config",
            )

        configured = code_cfg.get("inspectors", ["bandit"])
        if isinstance(configured, str):
            configured = [configured]
        configured = [str(name).lower() for name in configured]
        if "bandit" not in configured:
            return CheckResult(
                name="bandit_scanner",
                status=CheckStatus.PASS,
                message=(
                    "Bandit not selected; configured code inspectors: "
                    + ", ".join(configured)
                ),
            )

        if importlib.util.find_spec("bandit") is None:
            return CheckResult(
                name="bandit_scanner",
                status=CheckStatus.FAIL,
                message="Bandit not found — Bandit code inspection will be SKIPPED",
                fix_hint="uv tool install --force ai-guardian",
            )

        try:
            from importlib.metadata import version as pkg_version

            bandit_version = pkg_version("bandit")
        except Exception:
            bandit_version = "unknown"

        return CheckResult(
            name="bandit_scanner",
            status=CheckStatus.PASS,
            message=f"Bandit (code inspector) v{bandit_version} installed",
        )

    def check_email_auth(self) -> CheckResult:
        """Warn if SMTP credentials are hardcoded in config (inline auth)."""
        self._ensure_config()
        if not self._config:
            return CheckResult(
                name="email_auth",
                status=CheckStatus.SKIP,
                message="No config loaded",
            )

        support = self._config.get("support", {})
        email = support.get("email", {})
        auth = email.get("auth", {})
        method = auth.get("method", "none")

        if method == "inline":
            return CheckResult(
                name="email_auth",
                status=CheckStatus.WARN,
                message=(
                    "SMTP credentials are hardcoded in config (auth.method=inline). "
                    "Use env var auth (method=env) for better security."
                ),
            )

        destination = support.get("export_destination", "")
        if destination.startswith("mailto:") or "@" in destination:
            if not email.get("smtp_host"):
                return CheckResult(
                    name="email_auth",
                    status=CheckStatus.WARN,
                    message=(
                        "Email destination configured but no SMTP host set. "
                        "Bundle will use system mailto: fallback."
                    ),
                )

        return CheckResult(
            name="email_auth",
            status=CheckStatus.PASS,
            message="Email auth OK",
        )

    def check_daemon_rest_port(self) -> CheckResult:
        """Warn if the running daemon's PID file is missing rest_port (REST API failed to bind)."""
        try:
            from ai_guardian.daemon import get_pid_path, is_pid_alive
        except ImportError:
            return CheckResult(
                name="daemon_rest_port",
                status=CheckStatus.SKIP,
                message="Daemon module not available",
            )

        pid_path = get_pid_path()
        if not pid_path.exists():
            return CheckResult(
                name="daemon_rest_port",
                status=CheckStatus.SKIP,
                message="Daemon not running",
            )

        try:
            import json as _json

            pid_info = _json.loads(pid_path.read_text())
        except Exception:
            return CheckResult(
                name="daemon_rest_port",
                status=CheckStatus.SKIP,
                message="Cannot read PID file",
            )

        pid = pid_info.get("pid", 0)
        if pid and not is_pid_alive(pid):
            return CheckResult(
                name="daemon_rest_port",
                status=CheckStatus.SKIP,
                message="Daemon process not alive",
            )

        rest_port = pid_info.get("rest_port", 0)
        if not rest_port:
            return CheckResult(
                name="daemon_rest_port",
                status=CheckStatus.WARN,
                message=(
                    "Daemon running but REST API did not start (rest_port missing from PID file). "
                    "Cache status, violations, and web console will be unavailable."
                ),
                fix_hint=(
                    "Check daemon log for 'REST API failed' warnings. "
                    "Stop any orphan daemon holding port 63152: "
                    "lsof -i :63152 | grep LISTEN, then kill <pid>. "
                    "Restart with: ai-guardian daemon restart"
                ),
            )

        return CheckResult(
            name="daemon_rest_port",
            status=CheckStatus.PASS,
            message=f"Daemon REST API running on port {rest_port}",
        )

    def check_version_currency(self) -> CheckResult:
        """Check if the installed version is current (uses cached PyPI data only)."""
        from ai_guardian import __version__

        self._ensure_config()
        update_cfg = (self._config or {}).get("update_checking", {})

        if not update_cfg.get("auto_check_on_doctor", True):
            return CheckResult(
                name="version_currency",
                status=CheckStatus.SKIP,
                message="Update checking disabled in config",
            )

        try:
            from ai_guardian.update_checker import (
                UpdateCheckCache,
                is_upgrade_available,
            )

            cache = UpdateCheckCache.load()
        except Exception:
            return CheckResult(
                name="version_currency",
                status=CheckStatus.SKIP,
                message=f"v{__version__} (no cached version data)",
                fix_hint="Run: ai-guardian check-update",
            )

        if cache is None or cache.latest_version is None:
            return CheckResult(
                name="version_currency",
                status=CheckStatus.SKIP,
                message=f"v{__version__} (no cached version data)",
                fix_hint="Run: ai-guardian check-update",
            )

        cache_ttl_days = update_cfg.get("cache_ttl_days", 7)
        if cache.is_stale(cache_ttl_days * 86400):
            return CheckResult(
                name="version_currency",
                status=CheckStatus.SKIP,
                message=f"v{__version__} (cached data expired)",
                fix_hint="Run: ai-guardian check-update",
            )

        if is_upgrade_available(__version__, cache.latest_version):
            return CheckResult(
                name="version_currency",
                status=CheckStatus.WARN,
                message=f"v{__version__} (v{cache.latest_version} available)",
                fix_hint="Run: ai-guardian upgrade",
            )

        return CheckResult(
            name="version_currency",
            status=CheckStatus.PASS,
            message=f"v{__version__} (latest)",
        )


# --- Output formatters ---

_STATUS_LABELS = {
    CheckStatus.PASS: "PASS",
    CheckStatus.WARN: "WARN",
    CheckStatus.FAIL: "FAIL",
    CheckStatus.SKIP: "SKIP",
}

_STATUS_COLORS = {
    CheckStatus.PASS: "\033[32m",  # green
    CheckStatus.WARN: "\033[33m",  # yellow
    CheckStatus.FAIL: "\033[31m",  # red
    CheckStatus.SKIP: "\033[90m",  # gray
}

_RESET = "\033[0m"

_CHECK_DISPLAY_NAMES = {
    "python_version": "Python version",
    "config_file": "Config file",
    "deprecated_fields": "Deprecated fields",
    "unknown_config_keys": "Unknown config keys",
    "global_pattern_server": "Global pattern server",
    "scanners": "Scanners",
    "pattern_server": "Pattern server",
    "ps_cache_path": "PS cache path",
    "ps_auth": "PS auth",
    "ps_url": "PS URL",
    "ps_cache_freshness": "PS cache freshness",
    "hooks": "Hooks",
    "state_dir": "State directory",
    "cache_dir": "Cache directory",
    "permissions": "Permissions",
    "directory_rules": "Directory rules",
    "console_deps": "Console deps",
    "tray_support": "System tray",
    "tkinter_support": "Tkinter",
    "ask_mode_deps": "Ask mode deps",
    "project_config": "Project config",
    "config_overlay": "Config overlay",
    "terminal_emulator": "Terminal emulator",
    "config_consistency": "Config consistency",
    "tighten_only": "Tighten-only policies",
    "self_protection": "Self-protection",
    "image_scanning": "Image scanning",
    "tray_plugins": "Tray plugins",
    "email_auth": "Email auth",
    "ml_detection": "ML detection",
    "ast_scanner": "AST scanning",
    "bandit_scanner": "Bandit (code security)",
    "daemon_rest_port": "Daemon REST port",
    "version_currency": "Version currency",
}


def _coerce_check_status(status: Union[CheckStatus, str]) -> CheckStatus:
    if isinstance(status, CheckStatus):
        return status
    try:
        return CheckStatus(status)
    except (TypeError, ValueError):
        return CheckStatus.SKIP


def _format_status(status: Union[CheckStatus, str], use_color: bool) -> str:
    status = _coerce_check_status(status)
    label = _STATUS_LABELS[status]
    if use_color:
        return f"{_STATUS_COLORS[status]}[{label}]{_RESET}"
    return f"[{label}]"


def format_human(report: DoctorReport) -> str:
    use_color = sys.stdout.isatty()
    lines = [f"ai-guardian doctor v{report.version}", ""]

    for check in report.checks:
        display_name = _CHECK_DISPLAY_NAMES.get(check.name, check.name)
        status_str = _format_status(check.status, use_color)

        if check.name == "hooks" and check.integrations is not None:
            line = f"  {status_str} {display_name:<20s}"
            lines.append(line.rstrip())
            for integration in check.integrations:
                integration_status = _format_status(
                    integration.get("status", CheckStatus.SKIP.value), use_color
                )
                integration_name = (
                    integration.get("display_name")
                    or integration.get("name")
                    or integration.get("ide", "integration")
                )
                integration_message = integration.get("message", "")
                lines.append(
                    f"       {' ' * 20}{integration_status} "
                    f"{integration_name:<32s} {integration_message}"
                )
                if integration.get("detail"):
                    for detail_line in str(integration["detail"]).split("\n"):
                        lines.append(f"       {' ' * 28} {detail_line}")
                if integration.get("fix_hint"):
                    prefix = "Fixed" if integration.get("fixed") else "Hint"
                    lines.append(
                        f"       {' ' * 28} {prefix}: {integration['fix_hint']}"
                    )

            if check.detail:
                for detail_line in check.detail.split("\n"):
                    lines.append(f"       {' ' * 20} {detail_line}")
            if check.fix_hint:
                prefix = "Fixed" if check.fixed else "Hint"
                lines.append(f"       {' ' * 20} {prefix}: {check.fix_hint}")
            continue

        line = f"  {status_str} {display_name:<20s} {check.message}"
        lines.append(line)

        if check.detail:
            for detail_line in check.detail.split("\n"):
                lines.append(f"       {' ' * 20} {detail_line}")

        if check.fix_hint:
            prefix = "Fixed" if check.fixed else "Hint"
            lines.append(f"       {' ' * 20} {prefix}: {check.fix_hint}")

    # Summary
    pass_count = sum(1 for c in report.checks if c.status == CheckStatus.PASS)
    warn_count = sum(1 for c in report.checks if c.status == CheckStatus.WARN)
    fail_count = sum(1 for c in report.checks if c.status == CheckStatus.FAIL)
    skip_count = sum(1 for c in report.checks if c.status == CheckStatus.SKIP)
    fixed_count = sum(1 for c in report.checks if c.fixed)

    parts = []
    if pass_count:
        parts.append(f"{pass_count} passed")
    if warn_count:
        parts.append(f"{warn_count} warning(s)")
    if fail_count:
        parts.append(f"{fail_count} error(s)")
    if skip_count:
        parts.append(f"{skip_count} skipped")
    if fixed_count:
        parts.append(f"{fixed_count} fixed")

    lines.append("")
    lines.append(f"  {', '.join(parts)}")

    return "\n".join(lines)


def check_result_to_dict(check: CheckResult) -> Dict[str, Any]:
    """Serialize a doctor check for CLI, REST, and other consumers."""
    data: Dict[str, Any] = {
        "name": check.name,
        "status": check.status.value,
        "message": check.message,
        "detail": check.detail,
        "fix_hint": check.fix_hint,
        "fixable": check.fixable,
        "fixed": check.fixed,
    }
    if check.integrations is not None:
        data["integrations"] = check.integrations
    return data


def format_json(report: DoctorReport) -> str:
    checks_data = [check_result_to_dict(check) for check in report.checks]

    pass_count = sum(1 for c in report.checks if c.status == CheckStatus.PASS)
    warn_count = sum(1 for c in report.checks if c.status == CheckStatus.WARN)
    fail_count = sum(1 for c in report.checks if c.status == CheckStatus.FAIL)
    skip_count = sum(1 for c in report.checks if c.status == CheckStatus.SKIP)
    fixed_count = sum(1 for c in report.checks if c.fixed)

    output = {
        "version": report.version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": len(report.checks),
            "pass": pass_count,
            "warn": warn_count,
            "fail": fail_count,
            "skip": skip_count,
            "fixed": fixed_count,
        },
        "checks": checks_data,
    }

    return json.dumps(output, indent=2)


# --- Helpers ---


def _tilde(path: Path) -> str:
    """Replace home directory with ~ for display."""
    try:
        return str(path).replace(str(Path.home()), "~")
    except Exception:
        return str(path)


# --- CLI entry point ---


def doctor_command(args) -> int:
    doctor = Doctor(
        fix=getattr(args, "fix", False),
        check_connectivity=getattr(args, "check_connectivity", False),
    )
    report = doctor.run_all()

    if getattr(args, "quiet", False):
        return report.exit_code

    if getattr(args, "json", False):
        print(format_json(report))
    else:
        print(format_human(report))

    return report.exit_code
