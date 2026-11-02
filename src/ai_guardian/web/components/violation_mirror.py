"""Attribution and source links for read-only mirrored violations."""

from urllib.parse import quote

from ai_guardian.daemon.violation_mirroring import _source_key
from ai_guardian.violations.utils import is_mirrored_violation


def mirror_source_link(violation: dict, service) -> str | None:
    """Return a Console route to the source record when its daemon is available."""
    if not is_mirrored_violation(violation) or service is None:
        return None
    mirror = violation.get("mirror", {})
    source_name = mirror.get("source_daemon")
    source_id = mirror.get("source_violation_id")
    if not isinstance(source_name, str) or not isinstance(source_id, str):
        return None
    try:
        targets = getattr(service, "targets", None)
        if targets is not None:
            matches = [target for target in targets if target.name == source_name]
            # Routes are keyed by daemon name. Do not create an ambiguous link
            # when multiple discovered daemons share that display name.
            if len(matches) != 1:
                return None
            target = matches[0]
        else:
            target = service.get_target_by_name(source_name)
    except Exception:
        return None
    if not target or target.status not in ("running", "paused"):
        return None
    expected_source_key = mirror.get("source_key")
    if (
        isinstance(expected_source_key, str)
        and _source_key(target) != expected_source_key
    ):
        return None
    return (
        f"/{quote(source_name, safe='')}/violation-detail"
        f"?id={quote(source_id, safe='')}"
    )


def render_mirror_attribution(violation: dict, service) -> None:
    """Render a clear read-only badge and an optional source-record link."""
    if not is_mirrored_violation(violation):
        return
    from nicegui import ui

    mirror = violation.get("mirror", {})
    source_name = mirror.get("source_daemon")
    label = source_name if isinstance(source_name, str) else "remote daemon"
    with ui.row().classes("items-center gap-2"):
        ui.badge("REMOTE · READ ONLY", color="blue-grey").classes("text-xs")
        ui.label(f"Mirrored from {label}").classes("text-xs text-grey-6")
        source_link = mirror_source_link(violation, service)
        if source_link:
            ui.link("Open source record ↗", source_link).classes("text-xs text-blue-4")
        else:
            ui.label("Source record unavailable").classes("text-xs text-grey-6")
