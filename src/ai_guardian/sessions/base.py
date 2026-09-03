"""SessionAdapter base class for IDE session discovery and reading."""

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional


class StepCollector(list):
    """Collect only one bounded page while an adapter parses a session.

    Adapters intentionally keep their format-specific parsing logic, but all
    of them append normalized steps to the same list.  Limiting storage here
    keeps page reads from retaining an entire transcript in memory while still
    allowing the parser to count steps and support arbitrary page offsets.
    ``offset=-1`` keeps the final page for newest-first views.
    """

    def __init__(self, offset: int = 0, limit: Optional[int] = None):
        super().__init__()
        self.offset = max(0, offset)
        self.limit = limit if limit is None or limit > 0 else 1
        self.total_count = 0
        self._tail = offset < 0
        self.summary = {
            "title": "",
            "model": "",
            "message_count": 0,
            "user_messages": 0,
            "assistant_messages": 0,
            "first_timestamp": "",
            "last_timestamp": "",
            "token_usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
        }

    def append(self, step):
        step_type = step.get("type") if isinstance(step, dict) else None
        if step_type == "user":
            self.summary["user_messages"] += 1
        elif step_type == "assistant":
            self.summary["assistant_messages"] += 1
        if step_type in ("user", "assistant"):
            self.summary["message_count"] += 1

        timestamp = step.get("timestamp", "") if isinstance(step, dict) else ""
        if timestamp:
            if not self.summary["first_timestamp"]:
                self.summary["first_timestamp"] = timestamp
            self.summary["last_timestamp"] = timestamp

        if isinstance(step, dict):
            if not self.summary["title"] and step_type == "title":
                self.summary["title"] = step.get("content", "")
            if not self.summary["model"] and step.get("model"):
                self.summary["model"] = step["model"]
            usage = step.get("usage", {})
            if isinstance(usage, dict):
                for key in self.summary["token_usage"]:
                    self.summary["token_usage"][key] += usage.get(key, 0) or 0

        if self._tail:
            super().append(step)
            if self.limit is not None and len(self) > self.limit:
                del self[0]
        elif self.limit is None:
            super().append(step)
        elif self.offset <= self.total_count < self.offset + self.limit:
            super().append(step)
        self.total_count += 1

    @property
    def page_offset(self) -> int:
        """Return the actual offset represented by this page."""
        if self._tail:
            return max(0, self.total_count - len(self))
        return self.offset


def iter_json_array_file(path: Path, chunk_size: int = 64 * 1024):
    """Yield values from a top-level JSON array without loading the array.

    A session can contain a very large JSON array (notably Cline and Gemini
    exports).  The standard ``json.load`` API materializes every record before
    the adapter can apply its page bound, so this small decoder keeps only the
    current record and the parser buffer in memory.
    """
    decoder = json.JSONDecoder()
    with open(path, "r", encoding="utf-8") as stream:
        buffer = stream.read(chunk_size)
        position = 0
        eof = not buffer

        def ensure_data():
            nonlocal buffer, eof
            if eof:
                return
            chunk = stream.read(chunk_size)
            if chunk:
                buffer += chunk
            else:
                eof = True

        def skip_whitespace():
            nonlocal position
            while True:
                while position >= len(buffer) and not eof:
                    ensure_data()
                while position < len(buffer) and buffer[position].isspace():
                    position += 1
                if position < len(buffer) or eof:
                    return

        while True:
            skip_whitespace()
            if position >= len(buffer):
                raise ValueError("Expected a JSON array")
            if buffer[position] != "[":
                raise ValueError("Expected a JSON array")
            position += 1
            break

        while True:
            skip_whitespace()
            if position >= len(buffer):
                raise ValueError("Unterminated JSON array")
            if buffer[position] == "]":
                return

            while True:
                try:
                    value, end = decoder.raw_decode(buffer, position)
                    break
                except json.JSONDecodeError:
                    if eof:
                        raise
                    ensure_data()

            yield value
            position = end
            skip_whitespace()
            if position >= len(buffer):
                raise ValueError("Unterminated JSON array")
            if buffer[position] == ",":
                position += 1
                if position > chunk_size:
                    buffer = buffer[position:]
                    position = 0
                continue
            if buffer[position] == "]":
                return
            raise ValueError("Expected a comma or array terminator")


class SessionAdapter:
    """Base class for per-IDE session adapters.

    Subclasses set ``name`` and ``session_dirs`` class attributes
    and override ``discover()`` and ``read_detail()``.
    """

    name: str = ""
    session_dirs: Dict = {}

    def resolve_session_dir(self) -> Optional[Path]:
        """Resolve session storage directory from env var or platform default."""
        info = self.session_dirs
        if not info:
            return None

        env_key = info.get("env", "")
        if env_key:
            env_val = os.environ.get(env_key, "")
            if env_val:
                return Path(os.path.expandvars(env_val)).expanduser()

        if sys.platform == "darwin":
            key = "default_mac"
        elif sys.platform == "win32":
            key = "default_win"
        else:
            key = "default_linux"

        default = info.get(key, "")
        if default:
            return Path(os.path.expandvars(default)).expanduser()

        return None

    def discover(
        self,
        project_path: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """Discover sessions for this IDE. Override in subclass."""
        return []

    def read_detail(
        self,
        session: Dict,
        offset: int = 0,
        limit: Optional[int] = None,
    ) -> List[Dict]:
        """Read full structured conversation steps. Override in subclass."""
        return []

    def read_detail_page(
        self, session: Dict, offset: int = 0, limit: int = 50
    ) -> StepCollector:
        """Read one bounded page of structured conversation steps.

        Adapters use ``StepCollector`` so the existing format parsers can be
        shared by full reads and page reads.  The parser may still scan the
        source to determine the total step count, but only the requested page
        remains attached to the returned result.
        """
        return self.read_detail(session, offset=offset, limit=limit)

    def read_summary(self, session: Dict) -> Dict:
        """Read enriched summary with timestamps and message counts."""
        result = dict(session)
        steps = self.read_detail(session)
        if not steps:
            return result
        user_count = sum(1 for s in steps if s.get("type") == "user")
        asst_count = sum(1 for s in steps if s.get("type") == "assistant")
        result["user_messages"] = user_count
        result["assistant_messages"] = asst_count
        timestamps = [s.get("timestamp", "") for s in steps if s.get("timestamp")]
        result["first_timestamp"] = timestamps[0] if timestamps else ""
        result["last_timestamp"] = timestamps[-1] if timestamps else ""
        return result

    def read_messages(self, session: Dict, limit: int = 200) -> List[Dict]:
        """Read messages from a session. Default returns empty list."""
        return []

    def _discover_generic_jsonl(
        self,
        project_path: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """Shared discovery for IDEs storing sessions as JSONL files."""
        base = self.resolve_session_dir()
        if not base or not base.is_dir():
            return []

        sessions = []
        try:
            jsonl_files = sorted(
                base.rglob("*.jsonl"),
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            return []

        for jf in jsonl_files[:limit]:
            try:
                stat = jf.stat()
                sessions.append(
                    {
                        "ide": self.name,
                        "session_id": jf.stem,
                        "project_path": "",
                        "file_path": str(jf),
                        "size_bytes": stat.st_size,
                        "modified": stat.st_mtime,
                        "title": "",
                        "model": "",
                        "message_count": 0,
                        "token_usage": {},
                    }
                )
            except OSError:
                continue

        return sessions[:limit]


def extract_tool_result_content(block: dict) -> tuple:
    """Extract (text, tool_use_id) from a tool_result content block."""
    rc = block.get("content", "")
    if isinstance(rc, list):
        rc = "\n".join(
            p.get("text", "") for p in rc if isinstance(p, dict) and p.get("text")
        )
    return str(rc), block.get("tool_use_id", "")


def truncate(text: str, max_len: int = 500) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."
