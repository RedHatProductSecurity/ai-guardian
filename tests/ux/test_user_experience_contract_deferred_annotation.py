"""UX contract for deferred source annotation (Issue #2162).

Scenario:
1. A hook scans content through a temporary file.
2. The violation retains a verified hash for the original source line.
3. The source file is still present and unchanged when the user opens the
   violation in the console.

Expected user experience:
- The console offers ``Suppress in Source...`` for the verified source line.
- A temporary-file violation without verifiable context remains config-only.
"""

import hashlib
import inspect
from unittest.mock import patch

import pytest

pytest.importorskip("nicegui", reason="NiceGUI requires Python >= 3.10")

from ai_guardian.violations.allowlist_context import get_annotation_target


def _temp_violation(source_path, line_number, line_hash=None):
    metadata = {
        "original_file_path": str(source_path),
        "line_content_hash": line_hash,
        "rule_id": "custom-rule",
    }
    return {
        "violation_type": "secret_detected",
        "blocked": {"file_path": "/tmp/scanner-copy.py", "line_number": line_number},
        "allowlist_context": metadata,
    }


def test_verified_context_restores_source_annotation_target(tmp_path):
    source = tmp_path / "config.py"
    source.write_text("safe\nvalue = SENSITIVE_VALUE\n", encoding="utf-8")
    line_hash = hashlib.sha256(b"value = SENSITIVE_VALUE").hexdigest()

    with patch(
        "ai_guardian.violations.allowlist_context.is_temp_path", return_value=False
    ):
        target = get_annotation_target(_temp_violation(source, 2, line_hash))

    assert target == (str(source), 2)


def test_unverified_temp_context_stays_config_only():
    violation = {
        "violation_type": "secret_detected",
        "blocked": {"file_path": "/tmp/scanner-copy.py", "line_number": 2},
    }
    assert get_annotation_target(violation) is None


def test_violation_views_use_verified_annotation_target():
    from ai_guardian.tui.violations import ViolationDetailsModal
    from ai_guardian.web.pages.violations import _render_violation_card

    tui_source = inspect.getsource(ViolationDetailsModal.compose)
    web_source = inspect.getsource(_render_violation_card)
    assert "get_annotation_target" in tui_source
    assert "get_annotation_target" in web_source
    assert "Suppress in Source..." in tui_source
    assert "Suppress in Source..." in web_source
