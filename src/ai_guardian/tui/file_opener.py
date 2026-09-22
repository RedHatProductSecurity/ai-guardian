"""Open a file in the user's preferred editor at a specific line."""

import logging
import platform
import shutil
import subprocess
from typing import List, Optional, Tuple, Union

logger = logging.getLogger(__name__)


def open_in_editor(
    file_path: str,
    line_number: Optional[int] = None,
) -> Tuple[bool, str]:
    """Open a file in the preferred editor, optionally at a specific line.

    Editor priority: VS Code -> Cursor -> system default.
    Non-blocking — launches the editor in the background.

    Returns (success, editor_name).
    """
    try:
        cmd, editor = _build_editor_command(file_path, line_number)
        subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=isinstance(cmd, str),
        )
        logger.debug("Opened %s in %s", file_path, editor)
        return True, editor
    except Exception as e:
        logger.warning("Failed to open file in editor: %s", e)
        return False, ""


def _build_editor_command(
    file_path: str,
    line_number: Optional[int] = None,
) -> Tuple[Union[List[str], str], str]:
    """Build the command to open a file in the best available editor."""
    line = line_number or 1

    for editor_bin, editor_name in [("code", "VS Code"), ("cursor", "Cursor")]:
        if shutil.which(editor_bin):
            return [editor_bin, "--goto", f"{file_path}:{line}"], editor_name

    system = platform.system()
    if system == "Darwin":
        return ["open", file_path], "system default"
    if system == "Linux":
        return ["xdg-open", file_path], "system default"
    if system == "Windows":
        return f'start "" "{file_path}"', "system default"

    raise OSError(f"Unsupported platform: {system}")
