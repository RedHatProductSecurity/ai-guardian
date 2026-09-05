"""Security Dashboard — comprehensive overview of all security features."""

from datetime import datetime, timezone

from nicegui import run, ui

from ai_guardian.web.client_state import is_client_deleted
from ai_guardian.web.components.header import create_header, create_sidebar
from ai_guardian.web.config_helpers import load_web_config

FEATURE_GROUPS = [
    (
        "Scanning",
        [
            (
                "secret_scanning",
                "Secret Scanning",
                "Scan for API keys, tokens, credentials",
            ),
            ("scan_pii", "PII Detection", "GDPR/CCPA compliance scanning"),
            (
                "image_scanning",
                "Image Scanning",
                "OCR-based image scanning for secrets and PII",
            ),
            (
                "transcript_scanning",
                "Transcript Scanning",
                "Scan conversation for secrets/PII from ! commands",
            ),
        ],
    ),
    (
        "Threat Detection",
        [
            (
                "prompt_injection",
                "Prompt Injection",
                "Detect and block prompt injection attacks",
            ),
            (
                "ssrf_protection",
                "SSRF Protection",
                "Block requests to private networks and metadata",
            ),
            (
                "config_file_scanning",
                "Config File Scanner",
                "Detect credential exfiltration in config files",
            ),
            (
                "context_poisoning",
                "Context Poisoning",
                "Detect context poisoning attempts",
            ),
            (
                "supply_chain",
                "Supply Chain",
                "Detect malicious hooks, MCP servers, and plugins",
            ),
            (
                "code_scanning",
                "Code Security",
                "Python code security scanning (Bandit)",
            ),
            (
                "scan_offensive",
                "Offensive Language",
                "Detect profanity, slurs, and non-inclusive terminology",
            ),
            (
                "canary_detection",
                "Canary Detection",
                "Detect user-registered tripwire values to catch data exfiltration",
            ),
            (
                "exfil_detection",
                "Exfil Detection",
                "Detect bash commands that steal credentials via curl, base64, key files, and cloud metadata",
            ),
        ],
    ),
    (
        "Response Protection",
        [
            (
                "secret_redaction",
                "Secret Redaction",
                "Redact secrets from tool outputs",
            ),
            ("annotations", "Annotations", "Inline suppression for secrets and PII"),
        ],
    ),
    (
        "Access Control",
        [
            ("permissions", "Permissions", "Tool permission enforcement"),
            (
                "security_instructions",
                "Security Instructions",
                "Security rule injection into AI context",
            ),
            (
                "directory_rules",
                "Directory Rules",
                "Block access to protected directories",
            ),
        ],
    ),
    (
        "Monitoring",
        [
            (
                "violation_logging",
                "Violation Logging",
                "Log blocked operations for audit",
            ),
            (
                "latency_tracking",
                "Latency Tracking",
                "Record per-hook timing to latency.jsonl",
            ),
        ],
    ),
]

FEATURE_PAGE_SLUGS = {
    "secret_scanning": "secrets",
    "scan_pii": "scan-pii",
    "prompt_injection": "pi-detection",
    "ssrf_protection": "ssrf",
    "config_file_scanning": "config-scanner",
    "context_poisoning": "context-poisoning",
    "secret_redaction": "secret-redaction",
    "annotations": "annotations",
    "permissions": "permission-rules",
    "directory_rules": "directory-rules",
    "violation_logging": "violation-logging",
    "latency_tracking": "performance",
    "code_scanning": "code-security",
    "scan_offensive": "offensive-language",
    "canary_detection": "canary-detection",
    "exfil_detection": "exfil-detection",
}


def _get_feature_status(config, key):
    if key == "permissions":
        return config.get("permissions", {}).get("enabled", True)
    if key == "security_instructions":
        si = config.get("security_instructions", {})
        if isinstance(si, dict):
            return si.get("inject_on_prompt", True)
        return True
    if key == "annotations":
        return config.get("annotations", {}).get("enabled", True)
    if key == "image_scanning":
        return config.get("image_scanning", {}).get("enabled", True)
    section = config.get(key, {})
    if isinstance(section, dict):
        enabled = section.get("enabled", True)
        if isinstance(enabled, dict):
            return enabled
        return enabled
    return True


def _parse_enabled(status):
    if isinstance(status, dict):
        disabled_until = status.get("disabled_until")
        if disabled_until:
            try:
                dt = datetime.fromisoformat(disabled_until.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) < dt:
                    return False, dt
            except (ValueError, TypeError):
                pass  # intentionally silent — invalid value uses default
            return True, None
        return status.get("value", True), None
    return bool(status), None


_DEFAULT_ACTIONS = {
    "secret_scanning": "block",
    "image_scanning": "block",
    "scan_pii": "block",
    "transcript_scanning": "scan",
    "prompt_injection": "block",
    "ssrf_protection": "block",
    "config_file_scanning": "block",
    "context_poisoning": "warn",
    "supply_chain": "block",
    "code_scanning": "warn",
    "scan_offensive": "log",
    "canary_detection": "block",
    "exfil_detection": "block",
    "secret_redaction": "warn",
    "annotations": "suppress",
    "permissions": "enforce",
    "security_instructions": "inject",
    "directory_rules": "block",
    "violation_logging": "log",
    "latency_tracking": "log",
}


def _get_action(config, key):
    section = config.get(key, {})
    if isinstance(section, dict):
        action = section.get("action")
        if action:
            return action
    return _DEFAULT_ACTIONS.get(key)


def _categorize_violation(reason):
    r = (reason or "").lower()
    if "ssrf" in r:
        return "SSRF Protection"
    if "jailbreak" in r:
        return "Jailbreak Detection"
    if "prompt injection" in r or "injection" in r:
        return "Prompt Injection"
    if "unicode" in r or "zero-width" in r or "homoglyph" in r:
        return "Unicode Attack"
    if "config" in r or "claude.md" in r or "agents.md" in r:
        return "Config File Scanner"
    if "pii" in r:
        return "PII Detection"
    if "secret" in r or "redact" in r:
        return "Secret Detection"
    if "image" in r or "ocr" in r:
        return "Image Scanning"
    if "transcript" in r:
        return "Transcript Scanning"
    if "permission" in r or "tool" in r or "skill" in r:
        return "Permissions"
    if "directory" in r:
        return "Directory Blocking"
    if "bandit" in r or "code security" in r or "insecure" in r:
        return "Code Security"
    return "Other"


def _load_recent_violations():
    from ai_guardian.web.config_helpers import load_web_violations

    result = load_web_violations(limit=100)
    violations = result.get("violations", []) if result else []
    now = datetime.now(timezone.utc)
    recent = []
    for v in violations:
        ts = v.get("timestamp", "")
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if (now - dt).total_seconds() <= 86400:
                recent.append(v)
        except (ValueError, TypeError):
            pass  # intentionally silent — best-effort operation
    return recent


def _load_total_violation_count():
    from ai_guardian.web.config_helpers import load_web_violations

    result = load_web_violations()
    violations = result.get("violations", []) if result else []
    return len(violations)


def _fmt_remaining(seconds):
    total = max(0, int(seconds))
    m = total // 60
    if m < 60:
        return f"{m}m"
    h = m // 60
    return f"{h}h {m % 60}m"


def create_dashboard_page(service, daemon_name: str):
    sidebar = create_sidebar(daemon_name, current=f"/{daemon_name}")
    create_header(daemon_name, drawer=sidebar)

    with ui.column().classes("flex-grow p-6 gap-4"):
        with ui.row().classes("items-center gap-4"):
            ui.label("Security Dashboard").classes("text-2xl font-bold")
            status_icon = ui.icon("circle").classes("text-grey text-sm")
            status_label = ui.label("—").classes("text-sm")

        content = ui.column().classes("w-full gap-4")
        violations_box = None

        async def refresh_violations():
            if is_client_deleted(ui.context.client):
                return
            if violations_box is None:
                return

            await run.io_bound(service.refresh_targets)
            target = service.get_target_by_name(daemon_name)
            if target:
                statuses = await run.io_bound(service.get_all_daemon_status)
                stats = None
                for e in statuses:
                    if e["target"].name == daemon_name:
                        stats = e["status"]
                        break
                if stats:
                    paused = stats.get("paused", False)
                    if paused:
                        status_icon._props["name"] = "pause_circle"
                        status_icon.classes(replace="text-amber text-sm")
                        remaining = stats.get("pause_remaining_seconds", 0)
                        if remaining > 0:
                            status_label.text = f"Paused ({_fmt_remaining(remaining)})"
                        else:
                            status_label.text = "Paused (indefinite)"
                    else:
                        status_icon._props["name"] = "check_circle"
                        status_icon.classes(replace="text-green text-sm")
                        status_label.text = "Running"
                    status_icon.update()
                else:
                    status_icon._props["name"] = "error"
                    status_icon.classes(replace="text-red text-sm")
                    status_label.text = "Unreachable"
                    status_icon.update()

            violations_box.clear()
            recent = await run.io_bound(_load_recent_violations)
            with violations_box:
                if recent:
                    cats = {}
                    for v in recent:
                        reason = v.get(
                            "reason",
                            v.get("violation_type", "Unknown"),
                        )
                        cat = _categorize_violation(reason)
                        cats[cat] = cats.get(cat, 0) + 1
                    ui.label(f"Total: {len(recent)} violations").classes("text-sm")
                    with ui.row().classes("gap-2 flex-wrap mt-1"):
                        for cat, count in sorted(
                            cats.items(),
                            key=lambda x: x[1],
                            reverse=True,
                        ):
                            ui.badge(f"{cat}: {count}", color="red").classes("text-xs")
                else:
                    ui.label("No violations in last 24 hours").classes(
                        "text-sm text-green"
                    )

        async def build_page():
            content.clear()
            config = await run.io_bound(load_web_config)

            all_features = []
            for _, features in FEATURE_GROUPS:
                for key, _, _ in features:
                    all_features.append(key)

            enabled_count = 0
            disabled_count = 0
            temp_disabled_count = 0
            for key in all_features:
                status = _get_feature_status(config, key)
                is_on, until = _parse_enabled(status)
                if until:
                    temp_disabled_count += 1
                elif is_on:
                    enabled_count += 1
                else:
                    disabled_count += 1

            total = len(all_features)

            with content:
                # --- Summary Bar ---
                with ui.row().classes("gap-4 flex-wrap"):
                    with ui.card().classes("items-center p-4"):
                        ui.label(str(total)).classes("text-3xl font-bold")
                        ui.label("Total").classes("text-sm text-grey-6")
                    with ui.card().classes("items-center p-4"):
                        ui.label(str(enabled_count)).classes(
                            "text-3xl font-bold text-green"
                        )
                        ui.label("Enabled").classes("text-sm text-grey-6")
                    with ui.card().classes("items-center p-4"):
                        clr = "text-red" if disabled_count else ""
                        ui.label(str(disabled_count)).classes(
                            f"text-3xl font-bold {clr}"
                        )
                        ui.label("Disabled").classes("text-sm text-grey-6")
                    if temp_disabled_count:
                        with ui.card().classes("items-center p-4"):
                            ui.label(str(temp_disabled_count)).classes(
                                "text-3xl font-bold text-amber"
                            )
                            ui.label("Temp Disabled").classes("text-sm text-grey-6")

                    on_scan_error = config.get("on_scan_error", "allow")
                    action = config.get("action", "block")
                    if isinstance(action, dict):
                        action = action.get("mode", "block")
                    with ui.card().classes("items-center p-4"):
                        ui.label(action.upper()).classes("text-lg font-bold")
                        ui.label("Action Mode").classes("text-sm text-grey-6")
                    with ui.card().classes("items-center p-4"):
                        ui.label(on_scan_error.upper()).classes("text-lg font-bold")
                        ui.label("On Error").classes("text-sm text-grey-6")

                # --- Feature Groups ---
                for group_name, features in FEATURE_GROUPS:
                    with ui.card().classes("w-full"):
                        ui.label(group_name).classes("text-lg font-bold")
                        with ui.row().classes("gap-3 flex-wrap mt-1"):
                            for key, label, desc in features:
                                status = _get_feature_status(config, key)
                                is_on, until = _parse_enabled(status)
                                action_val = _get_action(config, key)

                                if until:
                                    border = "orange"
                                    icon = "timer"
                                    status_text = "Temp Disabled"
                                    status_color = "text-amber"
                                elif is_on:
                                    border = "#4caf50"
                                    icon = "check_circle"
                                    status_text = "Enabled"
                                    status_color = "text-green"
                                else:
                                    border = "#f44336"
                                    icon = "cancel"
                                    status_text = "Disabled"
                                    status_color = "text-red"

                                slug = FEATURE_PAGE_SLUGS.get(key)
                                card_style = (
                                    f"border-left: 4px solid {border}; "
                                    "cursor: pointer"
                                    if slug
                                    else f"border-left: 4px solid {border}"
                                )
                                card = ui.card().classes("w-52").style(card_style)
                                if slug:
                                    card.on(
                                        "click",
                                        lambda dn=daemon_name, s=slug: ui.navigate.to(
                                            f"/{dn}/{s}"
                                        ),
                                    )
                                with card:
                                    with ui.row().classes("items-center gap-1"):
                                        ui.icon(icon).classes(f"{status_color} text-sm")
                                        ui.label(label).classes("font-bold text-sm")
                                    ui.label(desc).classes("text-xs text-grey-6")
                                    with ui.row().classes("items-center gap-2"):
                                        ui.label(status_text).classes(
                                            f"text-xs {status_color}"
                                        )
                                        if action_val:
                                            ui.badge(
                                                action_val,
                                                color="blue-grey",
                                            ).classes("text-xs")
                                    if until:
                                        remaining = until - datetime.now(timezone.utc)
                                        mins = max(
                                            0,
                                            int(remaining.total_seconds() / 60),
                                        )
                                        ui.label(f"{mins}m remaining").classes(
                                            "text-xs text-amber"
                                        )

                # --- Recent Violations (refreshed periodically) ---
                nonlocal violations_box
                with ui.card().classes("w-full"):
                    ui.label("Recent Violations (Last 24 Hours)").classes(
                        "text-lg font-bold"
                    )
                    violations_box = ui.column().classes("w-full")

                await refresh_violations()

                # --- Recommendations ---
                with ui.card().classes("w-full"):
                    ui.label("Recommendations").classes("text-lg font-bold")
                    recs = []
                    if disabled_count:
                        recs.append(
                            (
                                "warning",
                                f"{disabled_count} security feature(s) "
                                f"disabled. Enable them in Global Settings "
                                f"for maximum protection.",
                            )
                        )
                    if temp_disabled_count:
                        recs.append(
                            (
                                "info",
                                f"{temp_disabled_count} feature(s) temporarily "
                                f"disabled. They will re-enable automatically.",
                            )
                        )
                    total_v = await run.io_bound(_load_total_violation_count)
                    if total_v > 100:
                        recs.append(
                            (
                                "warning",
                                f"{total_v} total violations. Review the "
                                f"Violations page to identify patterns.",
                            )
                        )
                    if not recs:
                        recs.append(
                            (
                                "positive",
                                "All security features enabled — good "
                                "security posture!",
                            )
                        )
                        recs.append(
                            (
                                "info",
                                "Tip: Review the Violations page regularly "
                                "to monitor security events.",
                            )
                        )
                    recs.append(
                        (
                            "warning",
                            "Shell bypass: Commands with '!' prefix bypass "
                            "all hooks. Enable transcript_scanning for "
                            "after-the-fact detection.",
                        )
                    )

                    for severity, text in recs:
                        icon_map = {
                            "positive": ("check_circle", "text-green"),
                            "warning": ("warning", "text-amber"),
                            "info": ("lightbulb", "text-blue-4"),
                        }
                        ic, clr = icon_map.get(severity, ("info", "text-grey-6"))
                        with ui.row().classes("items-start gap-2"):
                            ui.icon(ic).classes(f"{clr} text-sm mt-1")
                            ui.label(text).classes("text-sm")

        ui.timer(0.1, build_page, once=True)
        ui.timer(30.0, refresh_violations)
