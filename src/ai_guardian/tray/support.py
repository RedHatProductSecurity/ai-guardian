"""Nonblocking tray support workflow; every native window owns a child process."""

import logging
import os
import threading
import uuid
from pathlib import Path

from ai_guardian.reporting import github_support as github
from ai_guardian.reporting import support_bundle as bundles
from ai_guardian.tray.notifications import show_notification

logger = logging.getLogger(__name__)
_review_lock = threading.Lock()


def _show_result(result: dict, info: dict) -> None:
    """Presentation failures must never misreport an already completed send."""
    path = info.get("temp_path", "")
    request = {
        "mode": "result",
        "request_id": uuid.uuid4().hex,
        "message": bundles._format_send_human(result),
        "temp_path": path if path and Path(path).is_dir() else "",
        "discussion_url": result.get("discussion_url", ""),
        "gist_url": result.get("gist_url", ""),
        "zip_path": (
            result.get("zip_path", "") if result.get("status") == "sent" else ""
        ),
    }
    try:
        github.review_dialog(request)
    except github.GitHubError:
        if result.get("delivery_status") == "zip_only":
            message = f"ZIP created locally: {result['zip_path']}. No files were uploaded or sent to support. The ZIP is not encrypted."
        elif result.get("delivery_status") == "local_only":
            message = f"Bundle exported locally to {result['destination']}. No Discussion was created."
        elif result.get("delivery_status") == "manual_required":
            message = f"Attach {result['zip_path']} in your mail client and send it yourself. AI Guardian has not sent an email."
        elif result.get("status") == "sent":
            url = result.get("discussion_url")
            message = (
                f"Support Discussion created: {url}"
                if url
                else "Support export completed."
            )
        elif result.get("delivery_status") == "uncertain":
            message = "Support outcome is uncertain. Check the destination before retrying; retain the local bundle."
        else:
            message = "Support did not complete. Check the destination before retrying and retain any local diagnostics."
        if result.get("gist_url"):
            message += f" Diagnostic Gist already uploaded: {result['gist_url']}. Open it to manage or delete it."
        show_notification("AI Guardian Support", message)


def run_support_flow(*, destination: str | None = None) -> dict:
    """Prepare local diagnostics, review choices, then send only on native consent."""
    info = {}
    started_send = False
    try:
        prepared = (
            bundles.prepare_bundle()
            if destination is None
            else bundles.prepare_bundle(export_destination=destination)
        )
        bundle_id = prepared["bundle_id"]
        info = bundles._active_bundles[bundle_id]
        if info["destination"] != github.DESTINATION:
            if not bundles._review_bundle_selection(bundle_id, info):
                return {
                    "status": "error",
                    "error_code": "cancelled",
                    "message": bundles.CANCELLED_MESSAGE,
                }
        # Public send performs the same file/category modal plus its separate
        # exact-content, identity-bound final consent. Never synthesize approval.
        started_send = True
        result = bundles.send_bundle(bundle_id)
        info = bundles._active_bundles.get(bundle_id, info)
    except github.GitHubError as exc:
        result = {"status": "error", "error_code": exc.code, "message": str(exc)}
    except Exception:
        # Collector or transport exceptions may contain private diagnostic data.
        logger.warning("Tray support workflow could not complete")
        result = {
            "status": "error",
            "error_code": "support",
            "delivery_status": "uncertain" if started_send else "not_sent",
            "message": (
                "Support outcome is uncertain. Check the destination and your GitHub Gists before retrying."
                if started_send
                else "Support preparation/review failed. Nothing was sent; retain any prepared files locally."
            ),
        }
        if started_send and info.get("destination") == github.DESTINATION:
            from ai_guardian.reporting.github_gist import recovery_url, uploaded_notice

            gist_url = recovery_url(info)
            if gist_url:
                result.update(
                    gist_url=gist_url,
                    message=result["message"] + uploaded_notice(gist_url),
                )
    if result.get("error_code") != "cancelled" or result.get("gist_url"):
        _show_result(result, info)
    return result


def _worker() -> None:
    try:
        run_support_flow()
    finally:
        _review_lock.release()


def open_support_dialog() -> bool:
    """Open one support workflow without blocking the tray or opening a shell."""
    from ai_guardian.ui.display import get_preferred_ui

    if get_preferred_ui() == "headless" or os.environ.get("AI_GUARDIAN_NO_TKINTER"):
        show_notification(
            "AI Guardian Support",
            "The support dialog needs a native desktop. Run 'ai-guardian support send --prepare' in your own terminal for the standalone workflow. Nothing was sent.",
        )
        return False
    if not _review_lock.acquire(blocking=False):
        show_notification("AI Guardian Support", "Support review is already open.")
        return False
    try:
        threading.Thread(target=_worker, name="support-review", daemon=True).start()
    except RuntimeError:
        _review_lock.release()
        logger.warning("Tray support worker could not start")
        show_notification(
            "AI Guardian Support",
            "The support dialog could not start. Nothing was sent.",
        )
        return False
    return True
