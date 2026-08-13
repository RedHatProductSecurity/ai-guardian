"""
Trace file reading and listing for the trace viewer feature.

Reads GuardedAgent trace files (single JSON per run) from a configured
directory.  Both the REST API and local MultiDaemonClient call into
this module.
"""

import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_FILENAME_PATTERN = re.compile(
    r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*_\d{8}-\d{6}_[a-f0-9]{8}\.json$"
)

_MODEL_PRICING = {
    "claude-sonnet-4-20250514": (3.00, 15.00),
    "claude-opus-4-20250514": (15.00, 75.00),
    "claude-haiku-3-5-20241022": (0.80, 4.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-opus-5": (15.00, 75.00),
    "claude-opus-4-6": (15.00, 75.00),
    "claude-fable-5": (3.00, 15.00),
}


def resolve_trace_dirs() -> List[str]:
    """Discover all unique trace directories from SDK agent profiles.

    Reads agent profiles from:
    1. The merged global/project config (``_load_config_file()``)
    2. All project configs known to the daemon (``active_project_dirs``)

    Resolves relative ``trace_dir`` paths against the config file's directory.
    Returns a list of unique absolute directory paths that exist on disk.
    """
    seen: set = set()
    dirs: List[str] = []

    _collect_trace_dirs_from_config(None, None, seen, dirs)
    _collect_from_daemon_projects(seen, dirs)

    if not dirs:
        fallback = os.path.join(os.getcwd(), "agents-trace")
        if os.path.isdir(fallback):
            dirs.append(fallback)

    return dirs


def _collect_trace_dirs_from_config(
    config: "Optional[Dict[str, Any]]",
    config_dir: "Optional[str]",
    seen: set,
    dirs: List[str],
) -> None:
    """Extract trace_dir values from a config dict and resolve paths."""
    if config is None:
        from ai_guardian.config.loaders import _load_config_file

        config, _ = _load_config_file()
        if not config:
            return

    sdk = config.get("sdk")
    if not isinstance(sdk, dict):
        return

    agents = sdk.get("agents")
    if not isinstance(agents, dict):
        return

    for profile_name, profile in agents.items():
        if not isinstance(profile, dict):
            continue
        trace_dir = profile.get("trace_dir")
        if not trace_dir or not isinstance(trace_dir, str):
            continue

        if os.path.isabs(trace_dir):
            abs_dir = trace_dir
        else:
            base = config_dir
            if base is None:
                from ai_guardian.config.loaders import _sdk_profile_key_base_dir

                base = _sdk_profile_key_base_dir("agents", profile_name, "trace_dir")
            if base is None:
                base = os.getcwd()
            abs_dir = os.path.join(base, trace_dir)

        abs_dir = os.path.normpath(abs_dir)
        if abs_dir not in seen and os.path.isdir(abs_dir):
            seen.add(abs_dir)
            dirs.append(abs_dir)


def _collect_from_daemon_projects(seen: set, dirs: List[str]) -> None:
    """Scan project configs known to the running daemon for trace_dir values."""
    try:
        from ai_guardian.daemon import get_daemon_state

        state = get_daemon_state()
        if state is None:
            return

        project_configs = getattr(state, "_project_config_paths", {})
        for project_dir, config_path in project_configs.items():
            if not config_path:
                continue
            try:
                with open(config_path, "r", encoding="utf-8") as fh:
                    project_config = json.load(fh)
            except (OSError, json.JSONDecodeError):
                continue
            config_dir = os.path.dirname(config_path)
            _collect_trace_dirs_from_config(project_config, config_dir, seen, dirs)
    except Exception:
        pass


def validate_filename(filename: str) -> bool:
    """Validate trace file path to prevent path traversal.

    Accepts both flat filenames (``agent_20260813_abc.json``) and
    relative paths with subdirectories (``subdir/agent_20260813_abc.json``).
    """
    if not filename or ".." in filename or "\\" in filename:
        return False
    if filename.startswith("/"):
        return False
    basename = filename.split("/")[-1]
    return bool(_FILENAME_PATTERN.match(basename))


def list_traces(
    trace_dirs: "str | List[str]",
    agent_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List trace files from one or more directories, returning metadata summaries.

    Reads each JSON file to extract top-level fields (agent_name, model,
    started_at, stop_reason, usage).  The full trace array is not parsed
    for the listing — only the top-level keys.

    Args:
        trace_dirs: Single directory path or list of directory paths.
        agent_name: Optional filter by agent_name (exact match).

    Returns list sorted by started_at descending.
    """
    if isinstance(trace_dirs, str):
        trace_dirs = [trace_dirs]

    summaries = []
    seen_paths: set = set()

    for trace_dir in trace_dirs:
        if not os.path.isdir(trace_dir):
            continue

        for dirpath, _dirnames, filenames in os.walk(trace_dir):
            for entry in filenames:
                if not entry.endswith(".json"):
                    continue
                filepath = os.path.join(dirpath, entry)
                rel_path = os.path.relpath(filepath, trace_dir)
                if rel_path in seen_paths:
                    continue

                summary = _read_trace_summary(filepath, rel_path)
                if summary is None:
                    continue

                if agent_name and summary.get("agent_name") != agent_name:
                    continue

                seen_paths.add(rel_path)
                summaries.append(summary)

    summaries.sort(key=lambda t: t.get("started_at", ""), reverse=True)
    return summaries


def _read_trace_summary(filepath: str, filename: str) -> Optional[Dict[str, Any]]:
    """Read a trace file and extract summary metadata."""
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("Skipping invalid trace file %s: %s", filename, exc)
        return None

    if not isinstance(doc, dict) or "agent_name" not in doc:
        return None

    usage = doc.get("usage") or {}
    trace = doc.get("trace") or []
    stop_reason = doc.get("stop_reason")

    total_turns = len(trace)
    violation_count = 0
    for turn_obj in trace:
        for step in turn_obj.get("steps", []):
            if step.get("type") == "scan":
                violation_count += len(step.get("violations") or [])

    started_at = doc.get("started_at", "")
    duration = _compute_duration(trace, started_at)

    try:
        file_mtime = os.path.getmtime(filepath)
    except OSError:
        file_mtime = 0.0

    return {
        "filename": filename,
        "agent_name": doc.get("agent_name", ""),
        "model": doc.get("model", ""),
        "started_at": started_at,
        "stop_reason": stop_reason,
        "is_active": stop_reason == "in_progress",
        "total_turns": total_turns,
        "total_tokens": {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
        },
        "duration_seconds": duration,
        "violation_count": violation_count,
        "file_mtime": file_mtime,
    }


def read_trace_detail(
    trace_dirs: "str | List[str]", filename: str
) -> Optional[Dict[str, Any]]:
    """Read a single trace file and return the full document with computed fields.

    Searches through one or more directories for the named file.
    """
    if not validate_filename(filename):
        return None

    if isinstance(trace_dirs, str):
        trace_dirs = [trace_dirs]

    filepath = None
    for trace_dir in trace_dirs:
        candidate = os.path.join(trace_dir, filename)
        if os.path.isfile(candidate):
            filepath = candidate
            break

    if filepath is None:
        return None

    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("Failed to read trace %s: %s", filename, exc)
        return None

    if not isinstance(doc, dict) or "agent_name" not in doc:
        return None

    usage = doc.get("usage") or {}
    trace = doc.get("trace") or []
    model = doc.get("model", "")
    stop_reason = doc.get("stop_reason")
    started_at = doc.get("started_at", "")

    computed = compute_token_summary(trace, usage, model)
    computed["duration_seconds"] = _compute_duration(trace, started_at)

    violations = []
    for turn_obj in trace:
        turn_num = turn_obj.get("turn", 0)
        for step in turn_obj.get("steps", []):
            if step.get("type") == "scan":
                step_violations = step.get("violations") or []
                if step_violations:
                    violations.append(
                        {
                            "turn": turn_num,
                            "step": step.get("step", 0),
                            "scanned": step.get("scanned", ""),
                            "violations": step_violations,
                        }
                    )

    computed["violation_count"] = sum(len(v["violations"]) for v in violations)
    computed["violations"] = violations

    doc["is_active"] = stop_reason == "in_progress"
    doc["computed"] = computed
    return doc


def compute_token_summary(trace: list, usage: dict, model: str) -> Dict[str, Any]:
    """Compute per-turn token breakdown, running totals, and cost estimate."""
    per_turn: List[Dict[str, Any]] = []
    for turn_obj in trace:
        turn_num = turn_obj.get("turn", 0)
        turn_input = 0
        turn_output = 0
        turn_cache_read = 0
        turn_cache_creation = 0

        for step in turn_obj.get("steps", []):
            if step.get("type") == "response":
                step_usage = step.get("usage") or {}
                turn_input += step_usage.get("input_tokens", 0)
                turn_output += step_usage.get("output_tokens", 0)
                turn_cache_read += step_usage.get("cache_read_input_tokens", 0)
                turn_cache_creation += step_usage.get("cache_creation_input_tokens", 0)

        per_turn.append(
            {
                "turn": turn_num,
                "input_tokens": turn_input,
                "output_tokens": turn_output,
                "cache_read_input_tokens": turn_cache_read,
                "cache_creation_input_tokens": turn_cache_creation,
            }
        )

    total_input = usage.get("input_tokens", 0)
    total_output = usage.get("output_tokens", 0)
    total_cache_read = usage.get("cache_read_input_tokens", 0)
    total_cache_creation = usage.get("cache_creation_input_tokens", 0)

    if total_input == 0 and total_output == 0 and per_turn:
        total_input = sum(t.get("input_tokens", 0) for t in per_turn)
        total_output = sum(t.get("output_tokens", 0) for t in per_turn)
        total_cache_read = sum(t.get("cache_read_input_tokens", 0) for t in per_turn)
        total_cache_creation = sum(
            t.get("cache_creation_input_tokens", 0) for t in per_turn
        )

    effective_usage = {
        "input_tokens": total_input,
        "output_tokens": total_output,
        "cache_read_input_tokens": total_cache_read,
        "cache_creation_input_tokens": total_cache_creation,
    }

    total_all_input = total_input + total_cache_read + total_cache_creation
    cache_hit_ratio = total_cache_read / total_all_input if total_all_input > 0 else 0.0

    return {
        "total_tokens": effective_usage,
        "per_turn_tokens": per_turn,
        "cost_estimate_usd": estimate_cost(model, effective_usage),
        "cache_hit_ratio": round(cache_hit_ratio, 4),
    }


def estimate_cost(model: str, usage: dict) -> float:
    """Estimate cost in USD using a hardcoded model pricing table.

    Returns 0.0 for unknown models.
    """
    pricing = None
    for key, rates in _MODEL_PRICING.items():
        if key in (model or ""):
            pricing = rates
            break

    if pricing is None:
        return 0.0

    input_price, output_price = pricing
    total_input = usage.get("input_tokens", 0)
    total_output = usage.get("output_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    cache_creation = usage.get("cache_creation_input_tokens", 0)

    cost = (total_input / 1_000_000) * input_price
    cost += (total_output / 1_000_000) * output_price
    cost += (cache_read / 1_000_000) * input_price * 0.1
    cost += (cache_creation / 1_000_000) * input_price * 1.25

    return round(cost, 6)


def _compute_duration(trace: list, started_at: str) -> float:
    """Compute duration in seconds from started_at to file mtime or last turn."""
    if not started_at:
        return 0.0
    try:
        start_dt = datetime.fromisoformat(started_at)
        from datetime import timezone

        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return max(0.0, (now - start_dt).total_seconds())
    except (ValueError, TypeError):
        return 0.0


def pushed_trace_to_summary(filename: str, doc: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a pushed trace document to a list summary dict."""
    usage = doc.get("usage") or {}
    trace = doc.get("trace") or []
    stop_reason = doc.get("stop_reason")

    violation_count = 0
    for turn_obj in trace:
        for step in turn_obj.get("steps", []):
            if step.get("type") == "scan":
                violation_count += len(step.get("violations") or [])

    return {
        "filename": filename,
        "agent_name": doc.get("agent_name", ""),
        "model": doc.get("model", ""),
        "started_at": doc.get("started_at", ""),
        "stop_reason": stop_reason,
        "is_active": stop_reason == "in_progress",
        "total_turns": len(trace),
        "total_tokens": {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
        },
        "duration_seconds": _compute_duration(trace, doc.get("started_at", "")),
        "violation_count": violation_count,
        "file_mtime": 0.0,
    }
