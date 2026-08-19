"""SessionAdapter base class for IDE session discovery and reading."""

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional


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

    def read_detail(self, session: Dict) -> List[Dict]:
        """Read full structured conversation steps. Override in subclass."""
        return []

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
