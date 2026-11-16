"""UX contract for trusted-session Console setting guidance."""

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")

from ai_guardian.web.pages.global_settings import DEVELOPER_SESSION_NON_BLOCKING_HELP


def test_console_explains_non_blocking_scope_and_remaining_protections():
    """USER EXPERIENCE: the setting explains why other hooks may still block.

    Scenario:
    1. A developer enables both trusted developer-session settings.
    2. A finding cannot be safely replaced, or a different enforcement hook blocks.
    3. The developer reads the setting help in the Global Settings Console.

    Expected User Experience:
    - The Console explains that sensitive findings need verified sanitization and
      host replacement to become advisory.
    - The Console makes clear that other protections and hooks remain active.
    - The developer is directed to review the violation and use the organization's
      approved exception process for legitimate development work.
    """
    help_text = DEVELOPER_SESSION_NON_BLOCKING_HELP

    assert "verified sanitized content" in help_text
    assert "otherwise it remains blocked" in help_text
    assert "other hooks may still block an operation" in help_text
    assert "review the violation" in help_text
    assert "organization's approved exception process" in help_text
    assert "on_scan_error" in help_text
