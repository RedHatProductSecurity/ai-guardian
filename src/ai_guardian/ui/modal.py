"""Runtime modal lifecycle: only proven pre-display failure permits fallback.

None, False, cancellation, timeout, and unknown failures are terminal outcomes.
The isolated child protocol never includes dialog contents in diagnostics.
"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import subprocess
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Callable, Mapping, TypeVar

from ai_guardian.ui.display import ui_provider_order
from ai_guardian.ui.monitor import (
    current_origin,
    monitor_origin,
    monitor_json_default,
    prepare_tk_display,
    placement_notice,
)

logger = logging.getLogger(__name__)
T = TypeVar("T")
_UNAVAILABLE = "__AI_GUARDIAN_MODAL_UNAVAILABLE__"


class UIUnavailable(RuntimeError):
    """The provider definitively failed before displaying any interaction."""


@dataclass
class _Lifecycle:
    displayed: bool = False


_lifecycle: ContextVar[_Lifecycle | None] = ContextVar("modal_lifecycle", default=None)


def run_modal(
    dialog_type: str,
    providers: Mapping[str, Callable[[], T]],
    *,
    fallback: T,
    screen_bounds=None,
    preferred=None,
) -> T:
    """Execute eligible implementations once, never retry a completed dialog."""
    screen_bounds = screen_bounds if screen_bounds is not None else current_origin()
    for provider in ui_provider_order(
        dialog_type, screen_bounds=screen_bounds, preferred=preferred
    ):
        if provider not in providers:
            continue
        state = _Lifecycle()
        token = _lifecycle.set(state)
        try:
            with monitor_origin(screen_bounds):
                return providers[provider]()
        except UIUnavailable:
            if state.displayed:
                logger.warning(
                    "Modal %s failed after display; not opening a replacement", provider
                )
                return fallback
            logger.warning(
                "Modal %s unavailable before display; trying next eligible provider",
                provider,
            )
        except Exception as exc:
            # Unknown visibility must not be interpreted as startup failure.
            logger.warning(
                "Modal %s ended with %s; not opening a replacement",
                provider,
                type(exc).__name__,
            )
            return fallback
        finally:
            _lifecycle.reset(token)
    return fallback


def create_tk_root():
    """Initialize Tk and track the first mapped root in the current attempt."""
    try:
        import tkinter as tk
    except ImportError as exc:
        raise UIUnavailable("Tk unavailable") from exc

    from ai_guardian.ui.display import _ensure_tcl_library

    try:
        _ensure_tcl_library()
        prepare_tk_display()
        root = tk.Tk()
    except (tk.TclError, OSError) as exc:
        raise UIUnavailable("Tk initialization unavailable") from exc

    state = _lifecycle.get()
    if state is not None:

        def mapped(event):
            if event.widget is root:
                state.displayed = True

        root.bind("<Map>", mapped, add="+")
    return root


def mark_modal_displayed() -> None:
    """Latch possible visibility before entering a panel without a Map event."""
    state = _lifecycle.get()
    if state is not None:
        state.displayed = True


def _find_free_port() -> int:
    """Return an available loopback port for a short-lived modal server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def run_nicegui_modal(title: str, *, dark=None, screen_bounds=None) -> None:
    """Run one browser modal, latching possible visibility before its launch.

    Capture the lifecycle now: server callbacks may execute in another context.
    Even a page error may already be visible in a tab, so it is terminal.
    """
    from nicegui import app, ui

    from ai_guardian.desktop_utils import open_url

    state = _lifecycle.get()
    port = _find_free_port()
    notice = placement_notice(
        screen_bounds if screen_bounds is not None else current_origin(), browser=True
    )
    if notice:
        # A regular browser can reuse a window on another monitor. Do not pretend
        # moveTo or opening a URL enforces placement; provide an explicit fallback.
        encoded_notice = json.dumps(notice).replace("<", "\\u003c")
        ui.add_head_html(
            "<script>document.addEventListener('DOMContentLoaded',()=>{"
            "const note=document.createElement('div');note.setAttribute('role','status');"
            "note.style.cssText='padding:12px;background:#fff3cd;color:#332701;white-space:normal';"
            f"note.textContent={encoded_notice};"
            "document.body.prepend(note);});</script>",
            shared=True,
        )

    def open_page():
        if state is not None:
            state.displayed = True
        open_url(f"http://127.0.0.1:{port}")

    app.on_disconnect(app.shutdown)
    app.on_startup(open_page)
    ui.run(
        host="127.0.0.1", port=port, title=title, dark=dark, show=False, reload=False
    )


def run_modal_child(callback: Callable[[], Any]) -> None:
    """Run a single isolated interaction, emitting only result/startup status."""
    state = _Lifecycle()
    token = _lifecycle.set(state)
    try:
        print(json.dumps(callback(), ensure_ascii=False), flush=True)
    except Exception as exc:
        if not state.displayed:
            print(_UNAVAILABLE, flush=True)
        logger.warning(
            "Modal child failed %s display (%s)",
            "after" if state.displayed else "before",
            type(exc).__name__,
        )
        raise SystemExit(1) from None
    finally:
        _lifecycle.reset(token)


def run_modal_subprocess(
    command: list[str], *, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Wait without a reading deadline; advance only on explicit startup failure."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={
                **os.environ,
                "PYTHONIOENCODING": "utf-8",
                "_AI_GUARDIAN_MODAL_MONITOR": json.dumps(
                    current_origin(), default=monitor_json_default
                ),
            },
            timeout=None,
            check=False,
            input=input_text,
        )
    except OSError as exc:
        raise UIUnavailable("Modal process could not start") from exc
    if result.returncode != 0:
        if _UNAVAILABLE in (result.stdout or "").splitlines():
            raise UIUnavailable("Modal child unavailable before display")
        raise RuntimeError("Modal child ended without a completed result")
    return result


def run_native_command(
    command: list[str], *, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Recognize only known native initialization failures, never arbitrary exits.

    Native command-line toolkits do not expose reliable map events. An unknown
    error could follow display, so it is terminal, even if stderr is nonempty.
    """
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8" if input_text is not None else None,
            input=input_text,
            timeout=None,
        )
    except OSError as exc:
        raise UIUnavailable("Native executable could not start") from exc
    error = getattr(result, "stderr", "")
    error = error if isinstance(error, str) else ""
    if result.returncode != 0 and (
        any(
            line.strip().startswith(detail)
            for line in error.lower().splitlines()
            for detail in (
                "cannot open display",
                "could not connect to display",
                "unable to init server",
                "failed to initialize gtk",
                "qt.qpa.xcb: could not connect to display",
                "qt.qpa.plugin: could not load the qt platform plugin",
                "could not load the qt platform plugin",
                "no qt platform plugin could be initialized",
            )
        )
        or any(
            re.fullmatch(
                r"\([^:\r\n]+:\d+\): gtk-warning \*\*: [0-9:.]+: cannot open display(?::.*)?",
                line.strip(),
            )
            for line in error.lower().splitlines()
        )
    ):
        raise UIUnavailable("Native display initialization failed")
    return result


def run_modal_channel(
    command: list[str],
    initial: dict[str, Any],
    on_event: Callable[[dict[str, Any]], dict[str, Any]],
) -> None:
    """Keep an isolated modal alive across explicit actions and status refreshes.

    JSON lines carry display snapshots and narrow user events, not backend
    objects. The child uses run_modal_child's existing startup-only signal.
    There is no user-reading deadline; EOF/unknown failures are terminal.
    """
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env={
                **os.environ,
                "PYTHONIOENCODING": "utf-8",
                "_AI_GUARDIAN_MODAL_MONITOR": json.dumps(
                    current_origin(), default=monitor_json_default
                ),
            },
        )
    except OSError as exc:
        raise UIUnavailable("Modal process could not start") from exc

    try:
        if process.stdin is None or process.stdout is None:
            raise RuntimeError("Modal channel unavailable")

        def respond(snapshot):
            assert process.stdin is not None
            process.stdin.write(
                json.dumps(snapshot, ensure_ascii=False, default=monitor_json_default)
                + "\n"
            )
            process.stdin.flush()

        respond(initial)
        while True:
            # Events contain only a row token, action and duration. Bound input
            # without cropping the complete display snapshot sent to the child.
            line = process.stdout.readline(65537)
            if not line or len(line) > 65536:
                raise RuntimeError("Modal channel ended without completion")
            if line.strip() == _UNAVAILABLE:
                raise UIUnavailable("Modal child unavailable before display")
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                # NiceGUI can emit startup information on stdout. Never echo it
                # into diagnostics or interpret it as permission to act.
                continue
            if event is None:
                return
            if not isinstance(event, dict):
                raise RuntimeError("Invalid modal event")
            mark_modal_displayed()
            respond(on_event(event))
    finally:
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass  # intentionally silent — channel cleanup
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
        except OSError:
            pass  # intentionally silent — child already exited during cleanup
