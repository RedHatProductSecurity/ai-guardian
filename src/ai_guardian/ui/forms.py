"""Reusable form flows; ordering and fallback belong exclusively to run_modal."""

from functools import partial
from typing import Any, Callable, TypeVar

from ai_guardian.ui.modal import mark_modal_displayed, run_modal
from ai_guardian.ui.native_form import NativeForm

T = TypeVar("T")
Form = Callable[..., dict[str, Any] | None]


def run_form_flow(interaction: Callable[[Form], T], *, screen_bounds=None) -> T | None:
    """Bind one provider for an entire simple-form interaction.

    Native supports a message or one text/checkbox field. Unsupported controls
    before display can advance to Tk. A completed first step latches visibility,
    so failure to start a later step can never restart the flow in another UI.
    Credentials and other private backend state stay in the caller's closure.
    """
    from ai_guardian.tray.sandbox_dialog import (
        _show_nicegui_form,
        _show_tkinter_form_subprocess,
    )

    def execute(renderer: Form) -> T:
        def form(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
            result = renderer(*args, **kwargs)
            mark_modal_displayed()
            return result

        return interaction(form)

    return run_modal(
        "basic_form",
        {
            "native": lambda: execute(NativeForm(screen_bounds=screen_bounds)),
            "tkinter": lambda: execute(
                partial(_show_tkinter_form_subprocess, screen_bounds=screen_bounds)
            ),
            "nicegui": lambda: execute(
                partial(_show_nicegui_form, screen_bounds=screen_bounds)
            ),
        },
        fallback=None,
        screen_bounds=screen_bounds,
    )
