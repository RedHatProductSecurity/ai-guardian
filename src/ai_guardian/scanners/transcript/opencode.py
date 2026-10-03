"""OpenCode transcript adapter — SQLite session database.

OpenCode stores conversation sessions in a SQLite database at
~/.local/share/opencode/opencode.db (or OPENCODE_HOME). This module
reads message parts to extract text for transcript scanning and assistant
message ``tokens`` objects to extract session usage.
"""

import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
from typing import Dict, List, Optional, Tuple

from ai_guardian.scanners.transcript.base import TranscriptAdapter
from ai_guardian.scanners.transcript.common import (
    _discover_path,
    _scan_transcript_text,
    _scan_with_position_tracking,
)

logger = logging.getLogger(__name__)

_DB_PATH_PATTERN = re.compile(
    r"(?P<path>(?:[A-Za-z]:[\\/]|/|~[\\/]|\.{1,2}[\\/])[^\s'\"]+\.db)"
)


def _query_opencode_db_path() -> Optional[str]:
    """Ask an installed OpenCode runtime for its active database path."""
    executable = shutil.which("opencode")
    if not executable:
        return None
    try:
        result = subprocess.run(
            [executable, "debug", "paths", "db"],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    output = "\n".join(((result.stdout or ""), (result.stderr or "")))
    for line in output.splitlines():
        candidate = line.strip().strip("'\"")
        match = _DB_PATH_PATTERN.search(candidate)
        if not match:
            continue
        path = os.path.expandvars(match.group("path")).strip("'\"")
        if os.path.isfile(os.path.expanduser(path)):
            return os.path.expanduser(path)
    return None


def get_opencode_db_path() -> Optional[str]:
    """Find OpenCode SQLite database path.

    Checks explicit V2 database configuration and the runtime's path command
    before retaining the V1 ``OPENCODE_HOME`` and XDG fallbacks.
    """
    explicit_db = os.environ.get("OPENCODE_DB")
    if explicit_db:
        if explicit_db == ":memory:":
            return None
        explicit_path = os.path.expanduser(os.path.expandvars(explicit_db))
        return explicit_path if os.path.isfile(explicit_path) else None

    legacy_path = _discover_path(
        "OPENCODE_HOME",
        "~/.local/share/opencode/opencode.db",
        check=os.path.exists,
        env_suffix="opencode.db",
    )
    if os.environ.get("OPENCODE_HOME"):
        return legacy_path
    return _query_opencode_db_path() or legacy_path


def _extract_token_usage(data: dict) -> Optional[Dict[str, int]]:
    """Map an OpenCode message ``tokens`` object to AI Guardian counters."""
    tokens = data.get("tokens")
    if not isinstance(tokens, dict):
        return None

    usage: Dict[str, int] = {}
    found_any = False

    for source_key, target_key in (
        ("input", "input_tokens"),
        ("output", "output_tokens"),
    ):
        value = tokens.get(source_key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        try:
            if value < 0:
                continue
            usage[target_key] = int(value)
        except (TypeError, ValueError, OverflowError):
            continue
        found_any = True

    cache = tokens.get("cache")
    if isinstance(cache, dict):
        for source_key, target_key in (
            ("read", "cache_read_input_tokens"),
            ("write", "cache_creation_input_tokens"),
        ):
            value = cache.get(source_key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            try:
                if value < 0:
                    continue
                usage[target_key] = int(value)
            except (TypeError, ValueError, OverflowError):
                continue
            found_any = True

    return usage if found_any else None


def parse_opencode_token_usage(
    db_path: Optional[str], session_id: Optional[str]
) -> Optional[Dict[str, int]]:
    """Sum usage from OpenCode ``message.data.tokens`` records.

    OpenCode stores aggregate usage on assistant messages, not on the
    transcript ``part`` records.  The current schema is:
    ``tokens.input``, ``tokens.output``, ``tokens.cache.read``, and
    ``tokens.cache.write``.  A result containing only zero counters is still
    considered available because the database explicitly supplied usage data.
    """
    if not db_path or not session_id or not os.path.isfile(db_path):
        return None

    totals: Dict[str, int] = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    found_any = False

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "SELECT data FROM message "
                "WHERE session_id = ? ORDER BY time_created ASC, id ASC",
                (session_id,),
            )
            for (data_str,) in rows:
                try:
                    data = json.loads(data_str)
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(data, dict):
                    continue

                usage = _extract_token_usage(data)
                if usage is None:
                    continue
                found_any = True
                for key in totals:
                    totals[key] += usage.get(key, 0)
        finally:
            conn.close()
    except (OSError, sqlite3.Error) as e:
        logger.debug(f"OpenCode token usage read error: {e}")
        return None

    return totals if found_any else None


def _extract_text_from_part(data: dict) -> str:
    """Extract scannable text from an OpenCode part data dict."""
    part_type = data.get("type")
    texts = []

    if part_type == "text":
        text = data.get("text", "")
        if text:
            texts.append(text)

    elif part_type == "tool":
        state = data.get("state")
        if isinstance(state, str):
            try:
                state = json.loads(state)
            except (json.JSONDecodeError, TypeError):
                state = None
        if isinstance(state, dict):
            output = state.get("output", "")
            if output:
                texts.append(output)
            input_data = state.get("input")
            if isinstance(input_data, dict):
                command = input_data.get("command", "")
                if command:
                    texts.append(command)

    return "\n".join(texts)


def read_opencode_transcript(
    db_path: str,
    session_id: str,
    since_timestamp: int = 0,
) -> Tuple[str, int]:
    """Read conversation text from OpenCode SQLite DB incrementally.

    Queries the ``part`` table for text and tool parts created after
    the given timestamp cursor.
    """
    texts = []
    latest_ts = since_timestamp

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            cursor = conn.execute(
                "SELECT data, time_created FROM part "
                "WHERE session_id = ? AND time_created > ? "
                "ORDER BY time_created ASC",
                (session_id, since_timestamp),
            )

            for data_str, ts in cursor:
                if ts > latest_ts:
                    latest_ts = ts

                try:
                    data = json.loads(data_str)
                except (json.JSONDecodeError, TypeError):
                    continue

                if not isinstance(data, dict):
                    continue

                extracted = _extract_text_from_part(data)
                if extracted:
                    texts.append(extracted)
        finally:
            conn.close()
    except sqlite3.Error as e:
        logger.debug(f"OpenCode DB read error: {e}")

    return "\n".join(texts), latest_ts


def get_opencode_latest_timestamp(db_path: str, session_id: str) -> int:
    """Get the latest part timestamp for a session (for first-scan skip)."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT MAX(time_created) FROM part WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row and row[0] is not None:
                return row[0]
        finally:
            conn.close()
    except sqlite3.Error as e:
        logger.debug(f"OpenCode DB timestamp query error: {e}")
    return 0


def scan_opencode_transcript_incremental(
    db_path: str,
    session_id: str,
    secret_config: Optional[Dict] = None,
    pii_config: Optional[Dict] = None,
    hook_context: Optional[Dict] = None,
    allowed_findings: Optional[set] = None,
) -> list:
    """Incrementally scan OpenCode session transcript via SQLite."""
    pos_key = f"opencode:{session_id}"

    combined_text = _scan_with_position_tracking(
        pos_key,
        reader_fn=lambda last_ts: read_opencode_transcript(
            db_path, session_id, last_ts
        ),
        init_position_fn=lambda: get_opencode_latest_timestamp(db_path, session_id),
        label="OpenCode",
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


class OpenCodeTranscriptAdapter(TranscriptAdapter):
    """Transcript adapter for OpenCode SQLite session database."""

    @property
    def name(self) -> str:
        return "OpenCode"

    def scan_incremental(
        self,
        hook_data: Dict,
        secret_config: Optional[Dict] = None,
        pii_config: Optional[Dict] = None,
        hook_context: Optional[Dict] = None,
        allowed_findings: Optional[set] = None,
    ) -> List[str]:
        db_path = get_opencode_db_path()
        session_id = hook_data.get("session_id")
        if not db_path or not session_id:
            logger.debug("OpenCode transcript: no DB path or session_id available")
            return []

        return scan_opencode_transcript_incremental(
            db_path,
            session_id,
            secret_config=secret_config,
            pii_config=pii_config,
            hook_context=hook_context,
            allowed_findings=allowed_findings,
        )
