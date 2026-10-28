"""Native, user-only support review. No network listener or auto-approve option.

Run only as a short-lived child so Tk owns the main thread on all platforms.
Input specifies what to display, never whether to approve. Only a user click
with an unchecked-by-default public consent checkbox can produce approval.
"""

import codecs
import json
import logging
import os
import re
import stat
import subprocess
import sys
from functools import partial
from pathlib import Path
from typing import Callable, NamedTuple

logger = logging.getLogger(__name__)
MAX_PREVIEW_BYTES = 1_000_000
DELIVERY_DESTINATIONS = {
    "Create ZIP only": "zip",
    "Gist + Discussion": "discussion",
}


def diagnostic_sort_key(name: str) -> tuple[bool, str, str]:
    """Keep Doctor first, then use case-insensitive alphabetical diagnostic names."""
    return name != "doctor.json", name.casefold(), name


class PreviewPage(NamedTuple):
    text: str
    next_offset: int | None = None
    total_bytes: int = 0


def is_log_file(name: str) -> bool:
    return Path(name).suffix.lower() == ".log" or bool(
        re.search(r"\.log\.\d+$", name, re.IGNORECASE)
    )


def truncate_text(
    text: str, name: str, limit: int, *, truncated: bool = False
) -> tuple[str, bool]:
    """Bound only log copies; structured diagnostics must remain complete."""
    if not is_log_file(name):
        return text, False
    raw = text.encode("utf-8")
    if len(raw) <= limit and not truncated:
        return text, False
    marker = "[Truncated: older content omitted; showing newest data.]\n"
    marker_raw = marker.encode("utf-8")[: max(0, limit)]
    budget = max(0, limit - len(marker_raw))
    retained = raw[-budget:] if budget else b""
    content = retained.decode("utf-8", errors="ignore")
    notice = marker_raw.decode("utf-8")
    return notice + content, True


def read_preview(
    directory: str, name: str, allowed: list[str], *, offset: int = 0
) -> PreviewPage:
    """Read one bounded UTF-8 page; every byte remains reachable and unchanged."""
    try:
        root = Path(directory)
        relative = Path(name)
        if (
            name not in allowed
            or not name
            or "\\" in name
            or relative.is_absolute()
            or ".." in relative.parts
            or root.is_symlink()
            or not root.is_dir()
            or not isinstance(offset, int)
            or offset < 0
        ):
            raise ValueError("Unreviewed file")
        path = root / relative
        current = root
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise ValueError("Linked file")
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("File outside review directory")
        fd = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
        )
        with os.fdopen(fd, "rb") as stream:
            attributes = os.fstat(stream.fileno())
            if not stat.S_ISREG(attributes.st_mode) or attributes.st_nlink > 1:
                raise ValueError("Unsupported file")
            if offset > attributes.st_size:
                raise ValueError("Unsupported offset")
            stream.seek(offset)
            limit = max(4, MAX_PREVIEW_BYTES)
            raw = stream.read(limit + 1)
        more = len(raw) > limit
        raw = raw[:limit]
        if b"\x00" in raw:
            raise UnicodeError("Binary content")
        decoder = codecs.getincrementaldecoder("utf-8")()
        text = decoder.decode(raw, final=not more)
        consumed = len(raw) - len(decoder.getstate()[0])
        return PreviewPage(
            text, offset + consumed if more else None, attributes.st_size
        )
    except UnicodeError:
        return PreviewPage(
            "Cannot preview: this file is not UTF-8 text. Leave it unchecked or review the prepared copy yourself."
        )
    except (OSError, ValueError, TypeError):
        return PreviewPage(
            "Cannot preview: the registered prepared file is unavailable or unsupported."
        )


def _show_file_preview(parent, request: dict, name: str) -> None:
    import tkinter as tk
    from tkinter import ttk
    from tkinter.scrolledtext import ScrolledText

    window = tk.Toplevel(parent)
    window.withdraw()
    window.title(f"Prepared diagnostic — {name}")
    window.geometry("900x650")
    _place_review_window(window, request, 900, 650)
    window.transient(parent)
    controls = ttk.Frame(window)
    controls.pack(side="bottom", fill="x", padx=12, pady=(0, 12))
    status = ttk.Label(window, wraplength=860)
    status.pack(anchor="w", padx=12, pady=(12, 0))
    content = ttk.Frame(window)
    content.pack(fill="both", expand=True, padx=12, pady=12)
    content.columnconfigure(0, weight=1)
    content.rowconfigure(0, weight=1)
    viewer = ScrolledText(content, wrap="none")
    viewer.grid(row=0, column=0, sticky="nsew")
    horizontal = ttk.Scrollbar(content, orient="horizontal", command=viewer.xview)
    horizontal.grid(row=1, column=0, sticky="ew")
    viewer.configure(xscrollcommand=horizontal.set)
    wrapping = tk.BooleanVar(value=False)

    def update_wrap():
        viewer.configure(wrap="word" if wrapping.get() else "none")
        if wrapping.get():
            horizontal.grid_remove()
        else:
            horizontal.grid()

    offsets = [0]
    index = 0
    page = PreviewPage("")

    def render():
        nonlocal page
        page = read_preview(
            request["temp_path"],
            name,
            [item["name"] for item in request["files"]],
            offset=offsets[index],
        )
        viewer.configure(state="normal")
        viewer.delete("1.0", "end")
        viewer.insert("1.0", page.text)
        viewer.configure(state="disabled")
        status.configure(
            text=(
                f"Page {index + 1} · bytes {offsets[index]}–{page.next_offset if page.next_offset is not None else page.total_bytes} of {page.total_bytes}. "
                "Use Next / Previous to view the complete file. Paging does not change exported content."
            )
        )
        previous.configure(state="normal" if index else "disabled")
        next_page.configure(
            state="normal" if page.next_offset is not None else "disabled"
        )

    def move(direction):
        nonlocal index
        if direction < 0 and index:
            index -= 1
        elif direction > 0 and page.next_offset is not None:
            offsets[index + 1 :] = [page.next_offset]
            index += 1
        else:
            return
        render()

    previous = ttk.Button(controls, text="Previous page", command=partial(move, -1))
    previous.pack(side="left")
    next_page = ttk.Button(controls, text="Next page", command=partial(move, 1))
    next_page.pack(side="left", padx=8)
    ttk.Checkbutton(
        controls, text="Wrap lines", variable=wrapping, command=update_wrap
    ).pack(side="left", padx=8)
    render()

    def close():
        window.destroy()
        parent.grab_set()

    ttk.Button(controls, text="Close", command=close).pack(side="right")
    window.protocol("WM_DELETE_WINDOW", close)
    _present_window(window)
    window.grab_set()
    parent.wait_window(window)


def _file_choices(
    frame, request: dict, on_change: Callable[[bool], None] | None = None
) -> dict:
    import tkinter as tk
    from tkinter import ttk

    toolbar = ttk.Frame(frame, style="Support.Card.TFrame")
    toolbar.pack(fill="x", pady=(0, 10))
    summary = ttk.Label(toolbar, style="Support.Muted.TLabel")
    summary.pack(side="left")
    choices: dict[str, tk.BooleanVar] = {}

    def update_count():
        selected = sum(bool(value.get()) for value in choices.values())
        summary.configure(text=f"{selected} of {len(choices)} files selected")
        if on_change is not None:
            on_change(bool(selected))

    def select_all(selected):
        for variable in choices.values():
            variable.set(selected)
        update_count()

    ttk.Button(toolbar, text="Deselect all", command=partial(select_all, False)).pack(
        side="right"
    )
    ttk.Button(toolbar, text="Select all", command=partial(select_all, True)).pack(
        side="right", padx=8
    )
    listing = ttk.Frame(frame, style="Support.Card.TFrame")
    listing.pack(fill="both", expand=True)
    canvas = tk.Canvas(listing, background="#ffffff", highlightthickness=0, height=250)
    scrollbar = ttk.Scrollbar(listing, orient="vertical", command=canvas.yview)
    scrollbar.pack(side="right", fill="y")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    rows = ttk.Frame(canvas, style="Support.Card.TFrame")
    rows.columnconfigure(0, weight=1)
    window = canvas.create_window((0, 0), window=rows, anchor="nw")
    rows.bind(
        "<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all"))
    )
    canvas.bind(
        "<Configure>", lambda event: canvas.itemconfigure(window, width=event.width)
    )
    ttk.Label(rows, text="FILE", style="Support.Column.TLabel").grid(
        row=0, column=0, sticky="ew", padx=8, pady=(0, 6)
    )
    ttk.Label(rows, text="REVIEW NOTES", style="Support.Column.TLabel", width=26).grid(
        row=0, column=1, sticky="ew", pady=(0, 6)
    )
    ttk.Label(rows, text="", style="Support.Column.TLabel", width=10).grid(
        row=0, column=2
    )
    included = request.get("include_files")
    if included is None:
        included = ["doctor.json"]
    files = sorted(request["files"], key=lambda item: diagnostic_sort_key(item["name"]))
    for index, item in enumerate(files, 1):
        name = item["name"]
        variable = tk.BooleanVar(value=name in included)
        choices[name] = variable
        ttk.Checkbutton(
            rows,
            text=name,
            variable=variable,
            command=update_count,
            style="Support.File.TCheckbutton",
        ).grid(row=index, column=0, sticky="ew", padx=8, pady=5)
        notes = f"{item.get('redactions', 0)} redactions"
        if item.get("truncated"):
            notes += " · truncated"
        ttk.Label(rows, text=notes, style="Support.Muted.TLabel", width=26).grid(
            row=index, column=1, sticky="w", padx=8
        )
        ttk.Button(
            rows,
            text="View",
            width=8,
            command=partial(_show_file_preview, frame.winfo_toplevel(), request, name),
        ).grid(row=index, column=2, padx=(8, 2), pady=5)
    update_count()
    return choices


def _open_destination_directory(zip_path: str) -> None:
    """Open the archive's containing folder, not the ZIP or an editor."""
    archive = Path(zip_path)
    if (
        not archive.is_absolute()
        or archive.suffix.lower() != ".zip"
        or not archive.is_file()
    ):
        raise ValueError("The local ZIP archive is unavailable")
    directory = str(archive.parent)
    if sys.platform == "win32":
        os.startfile(directory)
    else:
        subprocess.Popen(
            ["open" if sys.platform == "darwin" else "xdg-open", directory],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )


def _style_window(root) -> None:
    """Small scoped theme, confined to this isolated native window."""
    from tkinter import ttk

    style = ttk.Style(root)
    style.theme_use("clam")
    root.configure(background="#f4f6f8")
    style.configure("Support.TFrame", background="#f4f6f8")
    style.configure("Support.Card.TFrame", background="#ffffff")
    style.configure(
        "Support.TLabelframe",
        background="#ffffff",
        bordercolor="#d9e1ea",
        relief="solid",
    )
    style.configure(
        "Support.TLabelframe.Label",
        background="#f4f6f8",
        foreground="#334155",
        font=("sans-serif", 11, "bold"),
    )
    style.configure("Support.TLabel", background="#f4f6f8", foreground="#1f2937")
    style.configure(
        "Support.Heading.TLabel",
        background="#f4f6f8",
        foreground="#0f172a",
        font=("sans-serif", 18, "bold"),
    )
    style.configure("Support.Muted.TLabel", background="#ffffff", foreground="#64748b")
    style.configure(
        "Support.Column.TLabel",
        background="#ffffff",
        foreground="#64748b",
        font=("sans-serif", 9, "bold"),
    )
    style.configure(
        "Support.File.TCheckbutton",
        background="#ffffff",
        foreground="#1f2937",
        padding=4,
    )
    style.map("Support.File.TCheckbutton", background=[("active", "#eef4ff")])
    style.configure(
        "Support.Primary.TButton",
        background="#2563eb",
        foreground="#ffffff",
        padding=(18, 8),
        borderwidth=0,
    )
    style.map(
        "Support.Primary.TButton",
        background=[("disabled", "#cbd5e1"), ("active", "#1d4ed8")],
    )


def _present_window(root) -> None:
    """Map the finished dialog normally and request foreground focus once."""
    import tkinter as tk

    root.update_idletasks()
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        logger.debug("Support window manager does not accept a temporary raising hint")
    root.deiconify()
    root.lift()

    def focus():
        try:
            if root.winfo_exists():
                root.lift()
                root.focus_force()
        except tk.TclError:
            logger.debug("Support window closed before foreground focus")

    def release_topmost():
        try:
            if root.winfo_exists():
                root.attributes("-topmost", False)
        except tk.TclError:
            logger.debug("Temporary support window raising hint could not be cleared")

    root.after_idle(focus)
    root.after(200, release_topmost)


def _monitor_helpers():
    # Anchored installed stdlib-only code, never cwd/PYTHONPATH or a request path.
    # Keep the trusted reviewer usable with isolated, user-site-only installs.
    import runpy

    return runpy.run_path(str(Path(__file__).resolve().with_name("monitor.py")))


def _place_review_window(window, request, width, height):
    if request.get("screen_bounds") is not None:
        _monitor_helpers()["place_tk_window"](
            window, request["screen_bounds"], width, height
        )


def show_review(request: dict) -> dict | None:
    import tkinter as tk
    from tkinter import ttk
    from tkinter.scrolledtext import ScrolledText

    # Fixed metadata comes from the trusted backend, not client overrides.
    # Keep this child stdlib-only so isolated Python cannot import cwd or
    # PYTHONPATH code, including on user-site-only installations.
    mode = request["mode"]
    categories = request.get("categories", {})
    _monitor_helpers()["prepare_tk_display"]()
    root = tk.Tk()
    root.withdraw()  # Finish layout before mapping and requesting foreground focus.
    root.title(
        "AI Guardian — support result"
        if mode == "result"
        else "AI Guardian — Contact supports"
    )
    _style_window(root)
    root.geometry("960x820")
    root.minsize(650, 500)
    _place_review_window(root, request, 960, 820)
    result = None
    if request.get("screen_bounds") is not None:
        frame, buttons = _monitor_helpers()["tk_scrollable_content"](
            root, padding=20, style="Support.TFrame"
        )
    else:
        frame = ttk.Frame(root, padding=20, style="Support.TFrame")
        frame.pack(fill="both", expand=True)
        buttons = ttk.Frame(frame, style="Support.TFrame")
        # Non-tray layout remains unchanged; tray reviews reserve the footer
        # outside their scrollable viewport, including on small/scaled monitors.
        buttons.pack(side="bottom", fill="x", pady=(12, 0))
    ttk.Label(
        frame,
        text="Support result" if mode == "result" else "Contact supports",
        style="Support.Heading.TLabel",
    ).pack(anchor="w", pady=(0, 8))
    ttk.Label(
        frame,
        text=f"Source: {request.get('source', 'Local tray host')}",
        wraplength=860,
        style="Support.TLabel",
    ).pack(anchor="w", pady=(0, 6))
    if request.get("source", "Local tray host") != "Local tray host":
        ttk.Label(
            frame,
            text="Source-only diagnostics. View daemon-source.json for collection omissions; no tray-host diagnostics were substituted.",
            wraplength=860,
            style="Support.TLabel",
        ).pack(anchor="w", pady=(0, 6))
    if mode in ("edit", "upload", "approve"):
        ttk.Label(
            frame,
            text=f"Authenticated GitHub account: {request['account']}",
            style="Support.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            frame,
            text=request["warning"],
            wraplength=860,
            foreground="#9a3412",
            style="Support.TLabel",
        ).pack(anchor="w", pady=6)
    if "destination" in request and mode != "delivery":
        ttk.Label(
            frame,
            text=f"Final destination: {request['destination']}",
            wraplength=860,
            style="Support.TLabel",
        ).pack(anchor="w", pady=8)
    if request.get("local_only"):
        ttk.Label(
            frame,
            text="Local export only. No files will be sent to support and no Discussion will be created.",
            wraplength=860,
        ).pack(anchor="w")
    if request.get("zip_export"):
        ttk.Label(
            frame,
            text="Create a local ZIP only. No upload, GitHub login, email or support submission. The ZIP is not encrypted; review it before sharing.",
            wraplength=860,
            style="Support.TLabel",
        ).pack(anchor="w", pady=6)

    def close():
        root.destroy()

    if mode == "delivery":
        ttk.Label(
            frame,
            text="Choose how to share your support report",
            style="Support.TLabel",
        ).pack(anchor="w", pady=(20, 12))
        ttk.Label(frame, text="Destination", style="Support.TLabel").pack(
            anchor="w", pady=(0, 4)
        )
        destination = ttk.Combobox(
            frame, state="readonly", values=list(DELIVERY_DESTINATIONS)
        )
        destination.set("Create ZIP only")
        destination.pack(fill="x", pady=(0, 16))
        ttk.Label(
            frame,
            text=(
                "Create ZIP only keeps the selected diagnostics and your message on this computer. "
                "Nothing is uploaded or sent. You can forward the ZIP later through a support channel you choose. "
                "The ZIP is not encrypted.\n\n"
                "Gist + Discussion first asks approval to upload selected files to an unlisted Gist owned by your GitHub account. "
                "You then approve the exact public Discussion, including its Gist link. Unlisted is not private. "
                "Sanitization is not a guarantee of confidentiality."
            ),
            wraplength=860,
            style="Support.TLabel",
        ).pack(anchor="w")

        if request.get("gist_url"):
            ttk.Label(
                frame,
                text=f"Diagnostic Gist already uploaded: {request['gist_url']}. Choosing ZIP or Cancel does not delete it.",
                wraplength=860,
                style="Support.TLabel",
            ).pack(anchor="w", pady=12)

        def selected_delivery():
            delivery = DELIVERY_DESTINATIONS.get(destination.get())
            if delivery == "discussion" and not request.get("github_available", False):
                return None
            return delivery

        def choose_delivery():
            nonlocal result
            delivery = selected_delivery()
            if delivery is None:
                return
            result = {"request_id": request["request_id"], "delivery": delivery}
            close()

        next_button = ttk.Button(
            buttons,
            text="Next",
            command=choose_delivery,
            state="disabled",
            style="Support.Primary.TButton",
        )
        next_button.pack(side="right")

        def update_delivery(_event=None):
            next_button.configure(
                state="normal" if selected_delivery() is not None else "disabled"
            )

        destination.bind("<<ComboboxSelected>>", update_delivery)
        update_delivery()
        if not request.get("github_available", False):
            ttk.Label(
                frame,
                text="Gist + Discussion requires authenticated GitHub credentials. Sign in with GitHub CLI in your own terminal, then reopen support. Create ZIP only remains available without credentials.",
                wraplength=860,
                style="Support.TLabel",
            ).pack(anchor="w", pady=12)
    elif mode in ("edit", "bundle"):
        message_card = ttk.LabelFrame(
            frame, text="Your message", padding=12, style="Support.TLabelframe"
        )
        if mode == "edit":
            ttk.Label(frame, text="Discussion group", style="Support.TLabel").pack(
                anchor="w", pady=(8, 0)
            )
            category = ttk.Combobox(
                frame, state="readonly", values=list(categories.values())
            )
            category.set(categories[request["context"]["category"]])
            category.pack(fill="x")
            category_destination = ttk.Label(
                frame, wraplength=860, style="Support.TLabel"
            )
            category_destination.pack(anchor="w")

            def update_destination(_event=None):
                slug = next(
                    (
                        key
                        for key, value in categories.items()
                        if value == category.get()
                    ),
                    "",
                )
                category_destination.configure(
                    text=f"Public category destination: {request.get('destination', '')}/categories/{slug}"
                )

            category.bind("<<ComboboxSelected>>", update_destination)
            update_destination()
            ttk.Label(
                message_card, text="Title (required)", style="Support.Muted.TLabel"
            ).pack(anchor="w")
            title_value = tk.StringVar()
            title = ttk.Entry(message_card, textvariable=title_value)
            title.insert(0, request["context"]["title"])
            title.pack(fill="x")
        message_card.pack(fill="x", pady=(12, 10))
        ttk.Label(
            message_card,
            text="Message (required): describe the problem, what you expected, and how to reproduce it.",
            style="Support.Muted.TLabel",
        ).pack(anchor="w", pady=(4, 6))
        description = ScrolledText(
            message_card,
            height=4,
            wrap="word",
            background="#ffffff",
            foreground="#1f2937",
            relief="solid",
            borderwidth=1,
            padx=8,
            pady=6,
        )
        description.insert("1.0", request.get("context", {}).get("description", ""))
        description.pack(fill="x")
        files_card = ttk.LabelFrame(
            frame, text="Diagnostic files", padding=12, style="Support.TLabelframe"
        )
        files_card.pack(fill="both", expand=True, pady=6)
        action: ttk.Button | None = None

        def validation_message() -> str:
            if not any(variable.get() for variable in choices.values()):
                return "Select at least one file to include."
            if mode == "edit" and not title.get().strip():
                return "A support title is required."
            if not description.get("1.0", "end-1c").strip():
                return "A support message is required."
            return ""

        def update_action(*_args) -> None:
            if action is not None:
                message = validation_message()
                action.configure(state="disabled" if message else "normal")
                validation.configure(text=message)

        choices = _file_choices(files_card, request, on_change=update_action)
        ttk.Label(
            frame,
            text=(
                f"Prepared copies: {request['temp_path']}\n"
                "View files and select the ones you want to include. Only doctor.json is checked by default; saved choices are retained. Original CLI settings are unchanged. "
                "Delete any files you do not want to send from this directory before continuing."
            ),
            wraplength=860,
            style="Support.TLabel",
        ).pack(anchor="w", pady=(6, 0))
        if mode == "edit":
            ttk.Label(
                frame,
                text="Send opens the exact Gist upload review. Uploading needs your approval; publishing the Discussion and its Gist link then needs separate final consent.",
                wraplength=860,
                style="Support.TLabel",
            ).pack(anchor="w", pady=4)
        validation = ttk.Label(frame, foreground="#a83221", style="Support.TLabel")
        validation.pack(anchor="w")

        def preview():
            nonlocal result
            message = validation_message()
            if message:
                validation.configure(text=message)
                return
            included = [name for name, variable in choices.items() if variable.get()]
            if mode == "bundle":
                result = {
                    "request_id": request["request_id"],
                    "send": True,
                    "include_files": included,
                    "description": description.get("1.0", "end-1c"),
                }
            else:
                slug = next(
                    (
                        key
                        for key, value in categories.items()
                        if value == category.get()
                    ),
                    None,
                )
                if slug is None:
                    return
                result = {
                    "request_id": request["request_id"],
                    "category": slug,
                    "title": title.get(),
                    "description": description.get("1.0", "end-1c"),
                    "include_files": included,
                }
            close()

        action = ttk.Button(
            buttons,
            text="Create ZIP" if request.get("zip_export") else "Send",
            command=preview,
            state="disabled",
            style="Support.Primary.TButton",
        )
        action.pack(side="right")

        def description_changed(_event=None):
            if description.edit_modified():
                description.edit_modified(False)
                update_action()

        description.edit_modified(False)
        description.bind("<<Modified>>", description_changed)
        if mode == "edit":
            title_value.trace_add("write", update_action)
        update_action()
    elif mode in ("upload", "approve"):
        upload = mode == "upload"
        action_text = "Create Gist" if upload else "Publish publicly"
        ttk.Label(
            frame,
            text=f"Category: {request['category']}\n{'Gist description' if upload else 'Exact title'}: {request['title']}",
            wraplength=820,
        ).pack(anchor="w")
        ttk.Label(
            frame, text=f"Context redactions: {request['context_redactions']}"
        ).pack(anchor="w")
        ttk.Label(
            frame,
            text=(
                f"{len(request['files'])} diagnostic files to upload. Review their exact content below."
                if upload
                else f"{len(request['files'])} diagnostic files in your uploaded Gist. Review the exact Discussion and Gist link below."
            ),
            style="Support.TLabel",
        ).pack(anchor="w")
        consent_row = ttk.Frame(
            buttons if request.get("screen_bounds") is not None else frame,
            style="Support.TFrame",
        )
        consent_row.pack(
            side="top" if request.get("screen_bounds") is not None else "bottom",
            fill="x",
            pady=(8, 0),
        )
        ttk.Label(
            consent_row,
            text=f"Check the consent box below to enable {action_text}.",
            style="Support.TLabel",
            wraplength=860,
        ).pack(anchor="w")
        consent = tk.BooleanVar(value=False)

        def publish():
            nonlocal result
            if consent.get():
                result = {"request_id": request["request_id"], "approved": True}
                close()

        publish_button = ttk.Button(
            buttons,
            text=action_text,
            command=publish,
            state="disabled",
            style="Support.Primary.TButton",
        )
        publish_button.pack(side="right")
        consent_text = (
            "I approve uploading these exact files to an unlisted Gist owned by my GitHub account."
            if upload
            else "I reviewed the exact publication and approve making it public."
        )

        def update_consent():
            publish_button.configure(state="normal" if consent.get() else "disabled")

        if request.get("screen_bounds") is not None:
            # ttk checkbox text cannot wrap. Keep the full approval text next to
            # its unchecked control, outside the scrolling review on small screens.
            consent_controls = ttk.Frame(consent_row, style="Support.TFrame")
            consent_controls.pack(fill="x")
            ttk.Checkbutton(
                consent_controls, variable=consent, command=update_consent
            ).pack(side="left", anchor="n")
            consent_label = ttk.Label(
                consent_controls,
                text=consent_text,
                wraplength=520,
                style="Support.TLabel",
            )
            consent_label.pack(side="left", fill="x", expand=True)
            consent_controls.bind(
                "<Configure>",
                lambda event: consent_label.configure(
                    wraplength=max(1, event.width - 40)
                ),
            )
        else:
            ttk.Checkbutton(
                consent_row, text=consent_text, variable=consent, command=update_consent
            ).pack(anchor="w")
        body = ScrolledText(frame, wrap="word")
        body.insert("1.0", request["body"])
        body.configure(state="disabled")
        body.pack(fill="both", expand=True, pady=8)
        if not upload and request.get("gist_url"):
            ttk.Label(
                consent_row,
                text="The Gist is already uploaded. Cancel does not delete it; the result will show its link so you can manage or delete it.",
                wraplength=860,
                style="Support.TLabel",
            ).pack(anchor="w")
    elif mode == "result":
        message = ScrolledText(frame, wrap="word")
        message.insert("1.0", request["message"])
        message.configure(state="disabled")
        message.pack(fill="both", expand=True, pady=8)
        if request.get("temp_path"):
            ttk.Label(
                frame, text=f"Reviewed files: {request['temp_path']}", wraplength=860
            ).pack(anchor="w")
        zip_path = request.get("zip_path", "")
        if isinstance(zip_path, str) and zip_path:
            folder_status = ttk.Label(
                frame, foreground="#a83221", style="Support.TLabel", wraplength=860
            )
            folder_status.pack(anchor="w")

            def open_destination():
                try:
                    _open_destination_directory(zip_path)
                    folder_status.configure(text="")
                except (OSError, ValueError):
                    logger.warning("Support destination folder could not be opened")
                    folder_status.configure(
                        text="Could not open the destination folder. Use the ZIP path above to open it manually."
                    )

            ttk.Button(
                buttons, text="Open destination folder", command=open_destination
            ).pack(side="left")
        url = request.get("discussion_url", "")
        if isinstance(url, str) and re.fullmatch(
            r"https://github\.com/RedHatProductSecurity/ai-guardian/discussions/[1-9][0-9]*",
            url,
        ):
            import webbrowser

            ttk.Button(
                buttons, text="Open Discussion", command=lambda: webbrowser.open(url)
            ).pack(side="left")
        gist_url = request.get("gist_url", "")
        if isinstance(gist_url, str) and re.fullmatch(
            r"https://gist\.github\.com/[A-Za-z0-9-]{1,39}/[a-f0-9]{5,64}", gist_url
        ):
            import webbrowser

            ttk.Button(
                buttons, text="Open Gist", command=lambda: webbrowser.open(gist_url)
            ).pack(side="left")
    else:
        close()
        return None
    ttk.Button(
        buttons, text="Close" if mode == "result" else "Cancel", command=close
    ).pack(side="right", padx=8)
    root.protocol("WM_DELETE_WINDOW", close)
    if mode != "result":
        root.after(300_000, close)  # parent independently enforces approval expiry
    _present_window(root)
    root.grab_set()
    root.mainloop()
    return result


def main() -> int:
    try:
        request = json.load(sys.stdin)
        result = show_review(request)
        print(json.dumps(result))
        return 0
    except Exception:
        # UI startup errors may contain local paths or displayed content. The
        # backend emits a constant error, not the child's exception or stderr.
        logger.warning("Native support review could not be opened")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
