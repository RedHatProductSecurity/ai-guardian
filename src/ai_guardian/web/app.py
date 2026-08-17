"""
Web Console Application (NiceGUI).

Provides a browser-based dashboard for AI Guardian, connecting to daemons
via their REST APIs. Binds to localhost only for security.

Each daemon gets its own URL namespace: /{daemon_name}/...
Multiple browser tabs can view different daemons simultaneously.
"""

import atexit
import base64
import logging
import os
import socket
from pathlib import Path

from nicegui import app, ui

from ai_guardian.web.services.daemon_service import DaemonService

logger = logging.getLogger(__name__)


def _get_port_file():
    from ai_guardian.config.utils import get_state_dir

    return get_state_dir() / "web-console.port"


def _cleanup_port_file():
    try:
        _get_port_file().unlink(missing_ok=True)
    except OSError:
        pass  # intentionally silent — cleanup best-effort


def _write_port(port: int):
    try:
        port_file = _get_port_file()
        port_file.parent.mkdir(parents=True, exist_ok=True)
        port_file.write_text(str(port))
        logger.info("Web console on port %d", port)
    except OSError as e:
        logger.debug("Failed to write port file: %s", e)


class WebConsole:
    """Browser-based AI Guardian console powered by NiceGUI."""

    def __init__(self):
        self._service = DaemonService()
        from ai_guardian.web.config_helpers import set_daemon_service

        set_daemon_service(self._service)
        self._load_saved_theme()

    @staticmethod
    def _load_saved_theme():
        """Load preferred_theme from config and apply it."""
        try:
            from ai_guardian.config.utils import get_config_dir
            import json

            config_path = get_config_dir() / "ai-guardian.json"
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                name = config.get("console", {}).get("preferred_theme", "default")
                if name != "default":
                    from ai_guardian.theme import set_active_theme

                    set_active_theme(name)
        except Exception as e:
            logger.debug("Failed to load saved theme: %s", e)

    def run(self, host: str = "127.0.0.1", port: int = 0, show: bool = True):
        if host != "127.0.0.1":
            logger.warning("Web console binding to %s — exposed on network.", host)

        if port == 0:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind((host, 0))
            port = sock.getsockname()[1]
            sock.close()

        self._register_pages()
        atexit.register(_cleanup_port_file)
        _write_port(port)

        pkg_dir = Path(__file__).resolve().parent.parent
        images_dir = pkg_dir / "images"
        if not images_dir.is_dir():
            images_dir = pkg_dir.parent.parent / "images"
        if images_dir.is_dir():
            app.add_static_files("/images", str(images_dir))

        favicon_path = images_dir / "ai-guardian-320.png"
        favicon_value = "🛡️"
        if favicon_path.exists():
            try:
                b64 = base64.b64encode(favicon_path.read_bytes()).decode()
                favicon_value = f"data:image/png;base64,{b64}"
            except OSError:
                pass  # intentionally silent — best-effort operation

        if not os.environ.get("NICEGUI_STORAGE_PATH"):
            from ai_guardian.config.utils import get_state_dir

            storage_path = get_state_dir() / ".nicegui"
            try:
                storage_path.mkdir(parents=True, exist_ok=True)
            except OSError:
                storage_path = Path("/tmp/.nicegui")
                storage_path.mkdir(parents=True, exist_ok=True)
            os.environ["NICEGUI_STORAGE_PATH"] = str(storage_path)

        if show:
            from ai_guardian.desktop_utils import open_url

            url = f"http://{host}:{port}"
            app.on_startup(lambda: open_url(url))
            show = False

        ui.run(
            host=host,
            port=port,
            title="AI Guardian Web Console",
            dark=True,
            reload=False,
            show=show,
            favicon=favicon_value,
            storage_secret="ai-guardian-web-console",
        )

    def _register_pages(self):
        service = self._service

        @ui.page("/")
        def index_page():
            from ai_guardian.web.pages.daemon_picker import (
                create_daemon_picker_page,
            )

            create_daemon_picker_page(service)

        @ui.page("/{daemon_name}")
        def dashboard_page(daemon_name: str):
            from ai_guardian.web.pages.dashboard import create_dashboard_page

            create_dashboard_page(service, daemon_name)

        @ui.page("/{daemon_name}/settings")
        def settings_page(daemon_name: str):
            from ai_guardian.web.pages.global_settings import (
                create_global_settings_page,
            )

            create_global_settings_page(service, daemon_name)

        @ui.page("/{daemon_name}/violations")
        def violations_page(daemon_name: str):
            from ai_guardian.web.pages.violations import (
                create_violations_page,
            )

            create_violations_page(service, daemon_name)

        @ui.page("/{daemon_name}/violation-logging")
        def violation_logging_page(daemon_name: str):
            from ai_guardian.web.pages.violation_logging import (
                create_violation_logging_page,
            )

            create_violation_logging_page(service, daemon_name)

        @ui.page("/{daemon_name}/metrics")
        def metrics_page(daemon_name: str):
            from ai_guardian.web.pages.metrics import create_metrics_page

            create_metrics_page(service, daemon_name)

        @ui.page("/{daemon_name}/performance")
        def performance_page(daemon_name: str):
            from ai_guardian.web.pages.performance import create_performance_page

            create_performance_page(service, daemon_name)

        @ui.page("/{daemon_name}/logs")
        def logs_page(daemon_name: str):
            from ai_guardian.web.pages.logs import create_logs_page

            create_logs_page(service, daemon_name)

        @ui.page("/{daemon_name}/permission-rules")
        def permission_rules_page(daemon_name: str):
            from ai_guardian.web.pages.permission_rules import (
                create_permission_rules_page,
            )

            create_permission_rules_page(service, daemon_name)

        @ui.page("/{daemon_name}/skills")
        def skills_page(daemon_name: str):
            from ai_guardian.web.pages.skills import create_skills_page

            create_skills_page(service, daemon_name)

        @ui.page("/{daemon_name}/mcp-servers")
        def mcp_servers_page(daemon_name: str):
            from ai_guardian.web.pages.mcp_servers import (
                create_mcp_servers_page,
            )

            create_mcp_servers_page(service, daemon_name)

        @ui.page("/{daemon_name}/mcp-security")
        def mcp_security_page(daemon_name: str):
            from ai_guardian.web.pages.mcp_security import (
                create_mcp_security_page,
            )

            create_mcp_security_page(service, daemon_name)

        @ui.page("/{daemon_name}/permissions-discovery")
        def permissions_discovery_page(daemon_name: str):
            from ai_guardian.web.pages.permissions_discovery import (
                create_permissions_discovery_page,
            )

            create_permissions_discovery_page(service, daemon_name)

        @ui.page("/{daemon_name}/auto-directory-rules")
        def auto_directory_rules_page(daemon_name: str):
            from ai_guardian.web.pages.auto_directory_rules import (
                create_auto_directory_rules_page,
            )

            create_auto_directory_rules_page(service, daemon_name)

        @ui.page("/{daemon_name}/directory-rules")
        def directory_rules_page(daemon_name: str):
            from ai_guardian.web.pages.directory_rules import (
                create_directory_rules_page,
            )

            create_directory_rules_page(service, daemon_name)

        @ui.page("/{daemon_name}/secrets")
        def secrets_page(daemon_name: str):
            from ai_guardian.web.pages.secrets import create_secrets_page

            create_secrets_page(service, daemon_name)

        @ui.page("/{daemon_name}/secret-engines")
        def secret_engines_page(daemon_name: str):
            from ai_guardian.web.pages.secret_engines import (
                create_secret_engines_page,
            )

            create_secret_engines_page(service, daemon_name)

        @ui.page("/{daemon_name}/secret-redaction")
        def secret_redaction_page(daemon_name: str):
            from ai_guardian.web.pages.secret_redaction import (
                create_secret_redaction_page,
            )

            create_secret_redaction_page(service, daemon_name)

        @ui.page("/{daemon_name}/pi-detection")
        def pi_detection_page(daemon_name: str):
            from ai_guardian.web.pages.pi_detection import (
                create_pi_detection_page,
            )

            create_pi_detection_page(service, daemon_name)

        @ui.page("/{daemon_name}/pi-ml-engines")
        def pi_ml_engines_page(daemon_name: str):
            from ai_guardian.web.pages.pi_ml_engines import (
                create_pi_ml_engines_page,
            )

            create_pi_ml_engines_page(service, daemon_name)

        @ui.page("/{daemon_name}/pi-patterns")
        def pi_patterns_page(daemon_name: str):
            from ai_guardian.web.pages.pi_patterns import (
                create_pi_patterns_page,
            )

            create_pi_patterns_page(service, daemon_name)

        @ui.page("/{daemon_name}/pi-jailbreak")
        def pi_jailbreak_page(daemon_name: str):
            from ai_guardian.web.pages.pi_jailbreak import (
                create_pi_jailbreak_page,
            )

            create_pi_jailbreak_page(service, daemon_name)

        @ui.page("/{daemon_name}/pi-unicode")
        def pi_unicode_page(daemon_name: str):
            from ai_guardian.web.pages.pi_unicode import (
                create_pi_unicode_page,
            )

            create_pi_unicode_page(service, daemon_name)

        @ui.page("/{daemon_name}/context-poisoning")
        def context_poisoning_page(daemon_name: str):
            from ai_guardian.web.pages.context_poisoning import (
                create_context_poisoning_page,
            )

            create_context_poisoning_page(service, daemon_name)

        @ui.page("/{daemon_name}/supply-chain")
        def supply_chain_page(daemon_name: str):
            from ai_guardian.web.pages.supply_chain import (
                create_supply_chain_page,
            )

            create_supply_chain_page(service, daemon_name)

        @ui.page("/{daemon_name}/code-security")
        def code_security_page(daemon_name: str):
            from ai_guardian.web.pages.code_security import create_code_security_page

            create_code_security_page(service, daemon_name)

        @ui.page("/{daemon_name}/offensive-language")
        def offensive_language_page(daemon_name: str):
            from ai_guardian.web.pages.offensive_language import (
                create_offensive_language_page,
            )

            create_offensive_language_page(service, daemon_name)

        @ui.page("/{daemon_name}/canary-detection")
        def canary_detection_page(daemon_name: str):
            from ai_guardian.web.pages.canary_detection import (
                create_canary_detection_page,
            )

            create_canary_detection_page(service, daemon_name)

        @ui.page("/{daemon_name}/exfil-detection")
        def exfil_detection_page(daemon_name: str):
            from ai_guardian.web.pages.exfil_detection import (
                create_exfil_detection_page,
            )

            create_exfil_detection_page(service, daemon_name)

        @ui.page("/{daemon_name}/security-instructions")
        def security_instructions_page(daemon_name: str):
            from ai_guardian.web.pages.security_instructions import (
                create_security_instructions_page,
            )

            create_security_instructions_page(service, daemon_name)

        @ui.page("/{daemon_name}/ssrf")
        def ssrf_page(daemon_name: str):
            from ai_guardian.web.pages.ssrf import create_ssrf_page

            create_ssrf_page(service, daemon_name)

        @ui.page("/{daemon_name}/config-scanner")
        def config_scanner_page(daemon_name: str):
            from ai_guardian.web.pages.config_scanner import (
                create_config_scanner_page,
            )

            create_config_scanner_page(service, daemon_name)

        @ui.page("/{daemon_name}/scan-pii")
        def scan_pii_page(daemon_name: str):
            from ai_guardian.web.pages.scan_pii import (
                create_scan_pii_page,
            )

            create_scan_pii_page(service, daemon_name)

        @ui.page("/{daemon_name}/annotations")
        def annotations_page(daemon_name: str):
            from ai_guardian.web.pages.annotations import (
                create_annotations_page,
            )

            create_annotations_page(service, daemon_name)

        @ui.page("/{daemon_name}/remote-configs")
        def remote_configs_page(daemon_name: str):
            from ai_guardian.web.pages.remote_configs import (
                create_remote_configs_page,
            )

            create_remote_configs_page(service, daemon_name)

        @ui.page("/{daemon_name}/config-file")
        def config_file_page(daemon_name: str):
            from ai_guardian.web.pages.config_file import (
                create_config_file_page,
            )

            create_config_file_page(service, daemon_name)

        @ui.page("/{daemon_name}/config-editor")
        def config_editor_page(daemon_name: str):
            from ai_guardian.web.pages.config_editor import (
                create_config_editor_page,
            )

            create_config_editor_page(service, daemon_name)

        @ui.page("/{daemon_name}/console-settings")
        def console_settings_page(daemon_name: str):
            from ai_guardian.web.pages.console_settings import (
                create_console_settings_page,
            )

            create_console_settings_page(service, daemon_name)

        @ui.page("/{daemon_name}/config-effective")
        def config_effective_page(daemon_name: str):
            from ai_guardian.web.pages.config_effective import (
                create_config_effective_page,
            )

            create_config_effective_page(service, daemon_name)

        @ui.page("/{daemon_name}/detection-patterns")
        def detection_patterns_page(daemon_name: str):
            from ai_guardian.web.pages.detection_patterns import (
                create_detection_patterns_page,
            )

            create_detection_patterns_page(service, daemon_name)

        @ui.page("/{daemon_name}/regex-tester")
        def regex_tester_page(daemon_name: str):
            from ai_guardian.web.pages.regex_tester import (
                create_regex_tester_page,
            )

            create_regex_tester_page(service, daemon_name)

        @ui.page("/{daemon_name}/hook-simulator")
        def hook_simulator_page(daemon_name: str):
            from ai_guardian.web.pages.hook_simulator import (
                create_hook_simulator_page,
            )

            create_hook_simulator_page(service, daemon_name)

        @ui.page("/{daemon_name}/engine-tester")
        def engine_tester_page(daemon_name: str):
            from ai_guardian.web.pages.engine_tester import (
                create_engine_tester_page,
            )

            create_engine_tester_page(service, daemon_name)

        @ui.page("/{daemon_name}/directory-scan")
        def directory_scan_page(daemon_name: str):
            from ai_guardian.web.pages.directory_scan import (
                create_directory_scan_page,
            )

            create_directory_scan_page(service, daemon_name)

        @ui.page("/{daemon_name}/scan-configure")
        def scan_configure_page(daemon_name: str):
            from ai_guardian.web.pages.scan_configure import (
                create_scan_configure_page,
            )

            create_scan_configure_page(service, daemon_name)

        @ui.page("/{daemon_name}/health-check")
        def health_check_page(daemon_name: str):
            from ai_guardian.web.pages.health_check import (
                create_health_check_page,
            )

            create_health_check_page(service, daemon_name)

        @ui.page("/{daemon_name}/cache-status")
        def cache_status_page(daemon_name: str):
            from ai_guardian.web.pages.cache_status import (
                create_cache_status_page,
            )

            create_cache_status_page(service, daemon_name)

        @ui.page("/{daemon_name}/daemon")
        def daemon_detail_page(daemon_name: str):
            from ai_guardian.web.pages.daemon_detail import (
                create_daemon_detail_page,
            )

            create_daemon_detail_page(service, daemon_name)

        @ui.page("/{daemon_name}/sdk-agents")
        def sdk_agents_page(daemon_name: str):
            from ai_guardian.web.pages.sdk_agents import create_sdk_agents_page

            create_sdk_agents_page(service, daemon_name)

        @ui.page("/{daemon_name}/sdk-settings")
        def sdk_settings_page(daemon_name: str):
            from ai_guardian.web.pages.sdk_settings import create_sdk_settings_page

            create_sdk_settings_page(service, daemon_name)

        @ui.page("/{daemon_name}/ide-sessions")
        def ide_sessions_page(daemon_name: str):
            from ai_guardian.web.pages.ide_sessions import (
                create_ide_sessions_page,
            )

            create_ide_sessions_page(service, daemon_name)

        @ui.page("/{daemon_name}/ide-session-detail")
        def ide_session_detail_page(daemon_name: str):
            from ai_guardian.web.pages.ide_sessions import (
                create_ide_session_detail_page,
            )

            create_ide_session_detail_page(service, daemon_name)

        @ui.page("/{daemon_name}/traces")
        def traces_page(daemon_name: str):
            from ai_guardian.web.pages.traces import create_traces_page

            create_traces_page(service, daemon_name)

        @ui.page("/{daemon_name}/trace-detail")
        def trace_detail_page(daemon_name: str):
            from ai_guardian.web.pages.traces import create_trace_detail_page

            create_trace_detail_page(service, daemon_name)

        @ui.page("/{daemon_name}/otel-settings")
        def otel_settings_page(daemon_name: str):
            from ai_guardian.web.pages.otel_settings import create_otel_settings_page

            create_otel_settings_page(service, daemon_name)

        @ui.page("/{daemon_name}/about")
        def about_page(daemon_name: str):
            from ai_guardian.web.pages.about import create_about_page

            create_about_page(service, daemon_name)
