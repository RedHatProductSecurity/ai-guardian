"""Platform clipboard helpers shared by interactive UI components."""

import base64
import subprocess
import sys
from typing import Optional, Tuple


def copy_osc52(text: str) -> bool:
    """Copy text through the terminal OSC 52 escape sequence."""
    try:
        encoded = base64.b64encode(text.encode("utf-8")).decode("utf-8")
        sys.stdout.write(f"\033]52;c;{encoded}\a")
        sys.stdout.flush()
        return True
    except Exception:
        return False


def _try_clipboard_command(cmd: list, text: str, encoding: str = "utf-8") -> bool:
    """Try a clipboard command, returning True on success."""
    try:
        subprocess.run(
            cmd,
            input=text.encode(encoding),
            check=True,
            capture_output=True,
            timeout=5,
        )
        return True
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ):
        return False


def copy_to_system_clipboard(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Copy text using platform-native commands with an OSC 52 fallback."""
    if sys.platform == "darwin":
        if _try_clipboard_command(["pbcopy"], text):
            return (None, "pbcopy")
    elif sys.platform == "win32":
        if _try_clipboard_command(["clip"], text, encoding="utf-16le"):
            return (None, "clip")
    elif sys.platform.startswith("linux"):
        if _try_clipboard_command(["xclip", "-selection", "clipboard"], text):
            return (None, "xclip")
        if _try_clipboard_command(["xsel", "--clipboard", "--input"], text):
            return (None, "xsel")
        if _try_clipboard_command(["wl-copy"], text):
            return (None, "wl-copy")
        if copy_osc52(text):
            return (None, "OSC 52")
        return (
            "No native clipboard tool is available. Install xclip, xsel, or wl-copy",
            None,
        )
    else:
        if copy_osc52(text):
            return (None, "OSC 52")
        return ("Clipboard not supported on this platform", None)
