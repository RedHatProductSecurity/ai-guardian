"""
Remote trace cache — persist traces from remote daemons to local disk.

Provides push-on-write persistence (called from REST API when remote
daemons forward traces) and one-time catch-up pull (called from tray
on daemon discovery).  The web UI reads cached traces via
``list_cached_remote_traces()`` and ``read_cached_remote_trace()``.

Cache location: ``~/.local/state/ai-guardian/sdk/traces/_remote/<daemon>/``
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9_.-]")


def get_remote_cache_dir() -> Path:
    """Return the root directory for cached remote daemon traces."""
    from ai_guardian.config.utils import get_sdk_trace_dir

    return get_sdk_trace_dir() / "_remote"


def get_daemon_cache_dir(daemon_name: str) -> Path:
    """Return the cache directory for a specific daemon.

    Sanitizes the daemon name for safe filesystem use.
    """
    safe = _SAFE_NAME_RE.sub("_", daemon_name)
    if not safe or safe in (".", ".."):
        safe = "_unknown"
    return get_remote_cache_dir() / safe


def persist_trace(
    daemon_name: str, filename: str, trace_doc: Dict[str, Any]
) -> Optional[str]:
    """Write a full trace document and its meta sidecar to the cache.

    Returns the filepath on success, None on failure.
    """
    from ai_guardian.daemon.traces import validate_filename, write_trace_meta

    if not validate_filename(filename):
        logger.debug("Invalid trace filename rejected: %s", filename)
        return None

    cache_dir = get_daemon_cache_dir(daemon_name)
    filepath = os.path.join(str(cache_dir), filename)
    parent = os.path.dirname(filepath)
    os.makedirs(parent, exist_ok=True)

    try:
        with open(filepath, "w", encoding="utf-8") as fh:
            json.dump(trace_doc, fh, indent=2, default=str)
        write_trace_meta(filepath, trace_doc)
        return filepath
    except OSError:
        logger.debug("Failed to persist trace %s/%s", daemon_name, filename)
        return None


def persist_trace_meta(
    daemon_name: str, filename: str, summary: Dict[str, Any]
) -> Optional[str]:
    """Write a meta sidecar only (for in-progress traces).

    Returns the meta filepath on success, None on failure.
    """
    from ai_guardian.daemon.traces import validate_filename

    if not validate_filename(filename):
        return None

    cache_dir = get_daemon_cache_dir(daemon_name)
    filepath = os.path.join(str(cache_dir), filename)
    meta_fp = filepath.rsplit(".json", 1)[0] + ".meta.json"
    parent = os.path.dirname(meta_fp)
    os.makedirs(parent, exist_ok=True)

    meta = _summary_to_meta(summary)
    try:
        with open(meta_fp, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, separators=(",", ":"))
        return meta_fp
    except OSError:
        logger.debug("Failed to persist trace meta %s/%s", daemon_name, filename)
        return None


def _summary_to_meta(summary: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a trace listing summary to meta sidecar shape."""
    tokens = summary.get("total_tokens", {})
    meta: Dict[str, Any] = {
        "agent_name": summary.get("agent_name", ""),
        "model": summary.get("model", ""),
        "started_at": summary.get("started_at", ""),
        "stop_reason": summary.get("stop_reason"),
        "usage": {
            "input_tokens": tokens.get("input_tokens", 0),
            "output_tokens": tokens.get("output_tokens", 0),
            "cache_creation_input_tokens": tokens.get("cache_creation_input_tokens", 0),
            "cache_read_input_tokens": tokens.get("cache_read_input_tokens", 0),
        },
        "total_turns": summary.get("total_turns", 0),
        "violation_count": summary.get("violation_count", 0),
    }
    run_id = summary.get("run_id")
    if run_id:
        meta["run_id"] = run_id
    run_sequence = summary.get("run_sequence")
    if run_sequence is not None:
        meta["run_sequence"] = run_sequence
    return meta


def catchup_pull(client, target, max_fetches: int = 50) -> int:
    """One-time catch-up pull for a newly discovered remote daemon.

    Fetches the trace listing from the target, then downloads full
    trace documents for completed traces not already in the local cache.

    Returns the number of full traces fetched.
    """
    daemon_name = target.name
    try:
        result = client.get_traces(target, limit=None)
    except Exception:
        logger.debug("Catch-up pull failed for %s: listing error", daemon_name)
        return 0

    traces = (result or {}).get("traces", [])
    if not traces:
        return 0

    cache_dir = get_daemon_cache_dir(daemon_name)
    fetched = 0

    for t in traces:
        filename = t.get("filename", "")
        if not filename:
            continue

        full_path = os.path.join(str(cache_dir), filename)

        if t.get("stop_reason") == "in_progress" or t.get("is_active"):
            persist_trace_meta(daemon_name, filename, t)
            continue

        if os.path.isfile(full_path):
            continue

        if fetched >= max_fetches:
            persist_trace_meta(daemon_name, filename, t)
            continue

        try:
            detail = client.get_trace_detail(target, filename)
            if detail:
                persist_trace(daemon_name, filename, detail)
                fetched += 1
            else:
                persist_trace_meta(daemon_name, filename, t)
        except Exception:
            logger.debug("Failed to fetch trace detail %s/%s", daemon_name, filename)
            persist_trace_meta(daemon_name, filename, t)

    logger.info(
        "Catch-up pull for %s: %d full traces fetched, %d total listed",
        daemon_name,
        fetched,
        len(traces),
    )
    return fetched


def cleanup_stale_cache(retention_days: int = 90) -> int:
    """Delete cached trace files older than retention period.

    Uses file mtime for age determination. Removes empty directories
    after cleanup. Returns count of deleted files.
    """
    cache_root = get_remote_cache_dir()
    if not cache_root.is_dir():
        return 0

    cutoff = time.time() - (retention_days * 86400)
    deleted = 0

    for dirpath, dirnames, filenames in os.walk(str(cache_root), topdown=False):
        for entry in filenames:
            if not entry.endswith(".json"):
                continue
            filepath = os.path.join(dirpath, entry)
            try:
                if os.path.getmtime(filepath) < cutoff:
                    os.unlink(filepath)
                    deleted += 1
            except OSError:
                pass

        try:
            if dirpath != str(cache_root) and not os.listdir(dirpath):
                os.rmdir(dirpath)
        except OSError:
            pass

    return deleted


def prune_cache_before_date(
    cutoff_iso: str,
    include_local: bool = False,
    dry_run: bool = False,
) -> int:
    """Delete cached traces with started_at before a cutoff date.

    Args:
        cutoff_iso: ISO date string (YYYY-MM-DD).
        include_local: Also prune local traces, not just remote cache.
        dry_run: Print what would be deleted without deleting.

    Returns count of deleted (or would-delete) files.
    """
    try:
        cutoff = datetime.fromisoformat(cutoff_iso).replace(tzinfo=timezone.utc)
    except ValueError:
        logger.error("Invalid date format: %s", cutoff_iso)
        return 0

    dirs_to_prune = [str(get_remote_cache_dir())]
    if include_local:
        from ai_guardian.daemon.traces import resolve_trace_dirs

        dirs_to_prune.extend(resolve_trace_dirs())

    deleted = 0
    for trace_dir in dirs_to_prune:
        if not os.path.isdir(trace_dir):
            continue
        for dirpath, _dirnames, filenames in os.walk(trace_dir):
            for entry in filenames:
                if not entry.endswith(".json") or entry.endswith(".meta.json"):
                    continue
                filepath = os.path.join(dirpath, entry)
                started_at = _read_started_at(filepath)
                if started_at and started_at < cutoff:
                    if dry_run:
                        print(f"Would delete: {filepath}")
                    else:
                        os.unlink(filepath)
                        meta = filepath.rsplit(".json", 1)[0] + ".meta.json"
                        if os.path.exists(meta):
                            os.unlink(meta)
                    deleted += 1

    if not dry_run:
        _remove_empty_dirs(str(get_remote_cache_dir()))

    return deleted


def _read_started_at(filepath: str) -> Optional[datetime]:
    """Read started_at from meta sidecar or full trace file."""
    meta_fp = filepath.rsplit(".json", 1)[0] + ".meta.json"
    for fp in (meta_fp, filepath):
        try:
            with open(fp, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
            sa = doc.get("started_at", "")
            if sa:
                dt = datetime.fromisoformat(sa)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
        except (OSError, json.JSONDecodeError, ValueError):
            continue
    return None


def _remove_empty_dirs(root: str) -> None:
    """Remove empty subdirectories under root."""
    if not os.path.isdir(root):
        return
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        if dirpath == root:
            continue
        try:
            if not os.listdir(dirpath):
                os.rmdir(dirpath)
        except OSError:
            pass


def list_cached_remote_traces(
    agent_name: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """List all cached remote traces, tagged with daemon_source.

    Walks each subdirectory under ``_remote/`` and uses the existing
    ``list_traces()`` function to read metadata.
    """
    from ai_guardian.daemon.traces import list_traces

    cache_root = get_remote_cache_dir()
    if not cache_root.is_dir():
        return []

    all_traces: List[Dict[str, Any]] = []
    for entry in os.listdir(str(cache_root)):
        daemon_dir = cache_root / entry
        if not daemon_dir.is_dir():
            continue
        traces = list_traces(str(daemon_dir), agent_name)
        for t in traces:
            t["daemon_source"] = entry
        all_traces.extend(traces)

    all_traces.sort(key=lambda t: t.get("started_at", ""), reverse=True)
    if limit is not None and limit > 0:
        all_traces = all_traces[:limit]
    return all_traces


def read_cached_remote_trace(
    daemon_name: str, filename: str
) -> Optional[Dict[str, Any]]:
    """Read a full cached trace from the remote cache."""
    from ai_guardian.daemon.traces import read_trace_detail

    cache_dir = get_daemon_cache_dir(daemon_name)
    if not cache_dir.is_dir():
        return None
    return read_trace_detail(str(cache_dir), filename)
