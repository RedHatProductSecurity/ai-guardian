"""Cursor IDE transcript adapter — SQLite state.vscdb database.

Cursor stores conversation data in a SQLite key-value database at
``~/Library/Application Support/Cursor/User/globalStorage/state.vscdb``
(macOS). Individual messages are stored as JSON blobs under
``bubbleId:<composerId>:<bubbleId>`` keys in the ``cursorDiskKV`` table.
"""

import json
import logging
import os
import sqlite3
import sys
from typing import Dict, List, Optional, Set, Tuple

from ai_guardian.scanners.transcript.base import TranscriptAdapter
from ai_guardian.scanners.transcript.common import (
    _discover_path,
    _scan_transcript_text,
    _scan_with_position_tracking,
)

logger = logging.getLogger(__name__)


def get_cursor_db_path() -> Optional[str]:
    """Find Cursor SQLite database path.

    Checks CURSOR_DATA_DIR env var first, then platform-specific defaults.
    """
    if sys.platform == "darwin":
        default = "~/Library/Application Support/Cursor/User/globalStorage/state.vscdb"
    elif sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        default = os.path.join(
            appdata, "Cursor", "User", "globalStorage", "state.vscdb"
        )
    else:
        default = "~/.config/Cursor/User/globalStorage/state.vscdb"

    return _discover_path(
        "CURSOR_DATA_DIR",
        default,
        check=os.path.exists,
        env_suffix="state.vscdb",
    )


def _extract_text_from_bubble(data: dict) -> str:
    """Extract scannable text from a Cursor bubble JSON blob.

    Extracts text content from user/assistant messages and tool outputs.
    """
    texts = []

    text = data.get("text")
    if isinstance(text, str) and text:
        texts.append(text)

    tfd = data.get("toolFormerData")
    if isinstance(tfd, dict):
        output = tfd.get("output")
        if isinstance(output, str) and output:
            try:
                output_data = json.loads(output)
                if isinstance(output_data, dict):
                    inner_output = output_data.get("output", "")
                    if isinstance(inner_output, str) and inner_output:
                        texts.append(inner_output)
                    result = output_data.get("result", "")
                    if isinstance(result, str) and result:
                        texts.append(result)
                    contents = output_data.get("contents", "")
                    if isinstance(contents, str) and contents:
                        texts.append(contents)
                else:
                    texts.append(output)
            except (json.JSONDecodeError, TypeError):
                texts.append(output)

        raw_args = tfd.get("rawArgs")
        if isinstance(raw_args, str) and raw_args:
            try:
                args_data = json.loads(raw_args)
                if isinstance(args_data, dict):
                    for field in ("command", "content", "text"):
                        val = args_data.get(field)
                        if isinstance(val, str) and val:
                            texts.append(val)
            except (json.JSONDecodeError, TypeError):
                pass  # intentionally silent — skip unparseable tool args

    return "\n".join(texts)


def read_cursor_transcript(
    db_path: str,
    composer_id: str,
    seen_bubble_ids: Optional[Set[str]] = None,
) -> Tuple[str, Set[str]]:
    """Read conversation text from Cursor SQLite DB incrementally.

    Queries ``cursorDiskKV`` for ``bubbleId:<composer_id>:*`` keys.
    Only processes bubbles whose IDs are not in ``seen_bubble_ids``.

    Returns:
        Tuple of (combined_text, updated_seen_bubble_ids).
    """
    seen = set(seen_bubble_ids) if seen_bubble_ids else set()
    texts = []
    new_seen = set(seen)
    escaped_id = (
        composer_id.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
    prefix = f"bubbleId:{escaped_id}:"
    raw_prefix = f"bubbleId:{composer_id}:"

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            all_keys = conn.execute(
                "SELECT key FROM cursorDiskKV WHERE key LIKE ? ESCAPE '\\'",
                (prefix + "%",),
            ).fetchall()
            new_keys = [k for (k,) in all_keys if k[len(raw_prefix) :] not in seen]

            if new_keys:
                placeholders = ",".join("?" for _ in new_keys)
                cursor = conn.execute(
                    f"SELECT key, value FROM cursorDiskKV WHERE key IN ({placeholders})",
                    new_keys,
                )

                for key, value_blob in cursor:
                    bubble_id = key[len(raw_prefix) :]
                    new_seen.add(bubble_id)

                    try:
                        if isinstance(value_blob, bytes):
                            data = json.loads(
                                value_blob.decode("utf-8", errors="replace")
                            )
                        else:
                            data = json.loads(value_blob)
                    except (json.JSONDecodeError, TypeError):
                        continue

                    if not isinstance(data, dict):
                        continue

                    extracted = _extract_text_from_bubble(data)
                    if extracted:
                        texts.append(extracted)
            else:
                for (k,) in all_keys:
                    new_seen.add(k[len(raw_prefix) :])
        finally:
            conn.close()
    except sqlite3.Error as e:
        logger.debug(f"Cursor DB read error: {e}")

    return "\n".join(texts), new_seen


def get_cursor_bubble_ids(db_path: str, composer_id: str) -> Set[str]:
    """Get all bubble IDs for a composer (for first-scan skip)."""
    bubble_ids = set()
    prefix = f"bubbleId:{composer_id}:"

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            cursor = conn.execute(
                "SELECT key FROM cursorDiskKV WHERE key LIKE ?",
                (prefix + "%",),
            )
            for (key,) in cursor:
                bubble_ids.add(key[len(prefix) :])
        finally:
            conn.close()
    except sqlite3.Error as e:
        logger.debug(f"Cursor DB bubble ID query error: {e}")

    return bubble_ids


def scan_cursor_transcript_incremental(
    db_path: str,
    composer_id: str,
    secret_config: Optional[Dict] = None,
    pii_config: Optional[Dict] = None,
    hook_context: Optional[Dict] = None,
    allowed_findings: Optional[set] = None,
) -> list:
    """Incrementally scan Cursor session transcript via SQLite."""
    pos_key = f"cursor:{composer_id}"

    def _reader(last_pos):
        seen_ids = set(last_pos) if isinstance(last_pos, list) else set()
        text, new_seen = read_cursor_transcript(db_path, composer_id, seen_ids)
        return text, sorted(new_seen)

    combined_text = _scan_with_position_tracking(
        pos_key,
        _reader,
        init_position_fn=lambda: sorted(get_cursor_bubble_ids(db_path, composer_id)),
        label="Cursor",
    )

    if not combined_text:
        return []

    return _scan_transcript_text(
        combined_text,
        pos_key,
        secret_config,
        pii_config,
        hook_context,
        allowed_findings=allowed_findings,
    )


class CursorTranscriptAdapter(TranscriptAdapter):
    """Transcript adapter for Cursor IDE SQLite database."""

    @property
    def name(self) -> str:
        return "Cursor IDE"

    def scan_incremental(
        self,
        hook_data: Dict,
        secret_config: Optional[Dict] = None,
        pii_config: Optional[Dict] = None,
        hook_context: Optional[Dict] = None,
        allowed_findings: Optional[set] = None,
    ) -> List[str]:
        db_path = get_cursor_db_path()
        composer_id = hook_data.get("conversation_id") or hook_data.get("session_id")
        if not db_path or not composer_id:
            logger.debug("Cursor transcript: no DB path or composer_id available")
            return []

        return scan_cursor_transcript_incremental(
            db_path,
            composer_id,
            secret_config=secret_config,
            pii_config=pii_config,
            hook_context=hook_context,
            allowed_findings=allowed_findings,
        )
