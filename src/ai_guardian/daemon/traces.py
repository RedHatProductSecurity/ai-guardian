"""
Trace file reading and listing for the trace viewer feature.

Reads GuardedAgent trace files (single JSON per run) from the fixed
XDG state directory.  Both the REST API and local MultiDaemonClient
call into this module.
"""

import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_STALE_THRESHOLD_SECONDS = 300

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


class HookTraceWriter:
    """Accumulate one IDE hook session in the GuardedAgent trace format."""

    def __init__(
        self,
        session_id: str,
        *,
        adapter_name: Optional[str] = None,
        project_name: Optional[str] = None,
        trace_dir: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> None:
        from ai_guardian.config.utils import get_sdk_trace_dir

        self.session_id = session_id
        self.adapter_name = adapter_name or "IDE"
        self.project_name = project_name or ""
        self.run_id = run_id
        self.started_at = datetime.now(timezone.utc)
        self._turn = 0
        self._trace: List[Dict[str, Any]] = []
        self._model = ""
        self._agent_name = ""
        directory = trace_dir or str(get_sdk_trace_dir())
        timestamp = self.started_at.strftime("%Y%m%d-%H%M%S")
        fallback_name = self.project_name or self.adapter_name
        safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "-", fallback_name).strip("-.")
        safe_name = safe_name or "ide-session"
        self.filepath = os.path.join(
            directory, f"{safe_name}_{timestamp}_{uuid.uuid4().hex[:8]}.json"
        )

    def record(self, hook_data: Dict[str, Any], normalized, result: Dict) -> None:
        """Append a normalized hook event and persist the in-progress trace."""
        self._update_metadata(hook_data)
        event = normalized.event
        event_value = getattr(event, "value", str(event)).lower()
        steps: List[Dict[str, Any]] = []

        if event_value == "prompt":
            self._turn += 1
            steps.append({"type": "prompt", "text": normalized.prompt_text or ""})
        elif event_value in ("pretooluse", "beforereadfile"):
            steps.append(
                {
                    "type": "tool_call",
                    "name": normalized.tool_name or "unknown",
                    "input": normalized.tool_input or {},
                }
            )
        elif event_value == "posttooluse":
            steps.append(
                {
                    "type": "tool_result",
                    "name": normalized.tool_name or "unknown",
                    "content": normalized.tool_response,
                }
            )

        if event_value in ("prompt", "pretooluse", "beforereadfile", "posttooluse"):
            violations = []
            violation_type = result.get("_violation_type")
            if violation_type:
                violations.append(
                    {
                        "type": violation_type,
                        "action": "block" if result.get("_blocked") else "warn",
                    }
                )
            steps.append(
                {
                    "type": "scan",
                    "scanned": event_value,
                    "violations": violations,
                }
            )

        # Never persist content that the hook identified as unsafe.  Clean content
        # has already passed the same scanners that protect the IDE interaction.
        if result.get("_violation_type"):
            placeholder = f"[redacted: {result['_violation_type']}]"
            for step in steps:
                if step.get("type") == "prompt":
                    step["text"] = placeholder
                elif step.get("type") == "tool_call":
                    step["input"] = placeholder
                elif step.get("type") == "tool_result":
                    step["content"] = placeholder

        if steps:
            if self._turn == 0:
                self._turn = 1
            if not self._trace or self._trace[-1]["turn"] != self._turn:
                self._trace.append({"turn": self._turn, "steps": []})
            turn_steps = self._trace[-1]["steps"]
            for step in steps:
                step["step"] = len(turn_steps)
                turn_steps.append(step)
        self._write(stop_reason="in_progress")

    def finalize(self, token_usage: Optional[Dict[str, Any]] = None) -> None:
        """Finish the trace document when the IDE session ends."""
        self._write(stop_reason="session_end", token_usage=token_usage, final=True)

    def _update_metadata(self, hook_data: Dict[str, Any]) -> None:
        self._model = (
            hook_data.get("model") or hook_data.get("model_name") or self._model
        )
        self._agent_name = (
            hook_data.get("session_name")
            or hook_data.get("session_title")
            or hook_data.get("title")
            or hook_data.get("task_description")
            or hook_data.get("workspace_name")
            or self._agent_name
        )

    def _document(
        self,
        stop_reason: str,
        token_usage: Optional[Dict[str, Any]] = None,
        final: bool = False,
    ) -> Dict[str, Any]:
        agent_name = self._agent_name or self.project_name
        if not agent_name:
            agent_name = f"{self.adapter_name} {self.started_at:%Y-%m-%d %H:%M:%S}"
        doc: Dict[str, Any] = {
            "agent_name": agent_name,
            "session_id": self.session_id,
            "model": self._model,
            "started_at": self.started_at.isoformat(),
            "stop_reason": stop_reason,
            "usage": token_usage or {},
            "project_name": self.project_name,
            "source": "hook",
            "adapter": self.adapter_name,
            "trace": self._trace,
        }
        if self.run_id:
            doc["run_id"] = self.run_id
        if final:
            doc["ended_at"] = datetime.now(timezone.utc).isoformat()
        return doc

    def _write(
        self,
        *,
        stop_reason: str,
        token_usage: Optional[Dict[str, Any]] = None,
        final: bool = False,
    ) -> None:
        doc = self._document(stop_reason, token_usage, final)
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        temporary_path = self.filepath + ".tmp"
        with open(temporary_path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2, default=str)
        os.replace(temporary_path, self.filepath)
        write_trace_meta(self.filepath, doc)


def _meta_path(filepath: str) -> str:
    """Return the ``.meta.json`` sidecar path for a trace file."""
    return filepath.rsplit(".json", 1)[0] + ".meta.json"


def write_trace_meta(filepath: str, doc: Dict[str, Any]) -> None:
    """Write a lightweight ``.meta.json`` sidecar next to a trace file.

    The sidecar contains only summary fields so ``list_traces()`` can
    avoid parsing the full (potentially multi-MB) trace array.
    """
    trace = doc.get("trace") or []
    usage = doc.get("usage") or {}
    stop_reason = doc.get("stop_reason")

    meta = {
        "agent_name": doc.get("agent_name", ""),
        "model": doc.get("model", ""),
        "started_at": doc.get("started_at", ""),
        "stop_reason": stop_reason,
        "usage": {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
        },
        "total_turns": len(trace),
        "violation_count": _count_violations(trace),
    }
    run_id = doc.get("run_id")
    if run_id:
        meta["run_id"] = run_id
    run_sequence = doc.get("run_sequence")
    if run_sequence is not None:
        meta["run_sequence"] = run_sequence

    meta_fp = _meta_path(filepath)
    try:
        with open(meta_fp, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, separators=(",", ":"))
    except OSError:
        logger.debug("Failed to write trace meta %s", meta_fp)


def _count_violations(trace: list) -> int:
    """Count total violations across all turns and scan steps."""
    count = 0
    for turn_obj in trace:
        for step in turn_obj.get("steps", []):
            if step.get("type") == "scan":
                count += len(step.get("violations") or [])
    return count


def _mark_trace_crashed(filepath: str) -> None:
    """Rewrite a stale in-progress trace file to stop_reason='crashed'."""
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
        if doc.get("stop_reason") != "in_progress":
            return
        doc["stop_reason"] = "crashed"
        mtime = os.path.getmtime(filepath)
        doc["ended_at"] = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
        with open(filepath, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2, default=str)
        write_trace_meta(filepath, doc)
    except Exception:
        logger.debug("Failed to mark trace as crashed: %s", filepath)


def resolve_trace_dirs() -> List[str]:
    """Return the fixed XDG state trace directory.

    Returns a single-element list containing the SDK trace directory
    (``~/.local/state/ai-guardian/sdk/traces/``).
    """
    from ai_guardian.config.utils import get_sdk_trace_dir

    return [str(get_sdk_trace_dir())]


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
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """List trace files from one or more directories, returning metadata summaries.

    Reads each JSON file to extract top-level fields (agent_name, model,
    started_at, stop_reason, usage).  The full trace array is not parsed
    for the listing — only the top-level keys.

    Args:
        trace_dirs: Single directory path or list of directory paths.
        agent_name: Optional filter by agent_name (exact match).
        limit: Maximum number of traces to return (after sorting).
            None means no limit.

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
                if not entry.endswith(".json") or entry.endswith(".meta.json"):
                    continue
                filepath = os.path.join(dirpath, entry)
                rel_path = os.path.relpath(filepath, trace_dir).replace("\\", "/")
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
    if limit is not None and limit > 0:
        summaries = summaries[:limit]
    return summaries


def _read_trace_summary(filepath: str, filename: str) -> Optional[Dict[str, Any]]:
    """Read a trace file and extract summary metadata.

    Prefers the lightweight ``.meta.json`` sidecar when available,
    falling back to a full parse of the trace file.
    """
    meta_fp = _meta_path(filepath)
    meta = _read_meta_sidecar(meta_fp)

    if meta is None:
        meta = _parse_full_trace_for_summary(filepath, filename)

    if meta is None:
        return None

    stop_reason = meta.get("stop_reason")
    started_at = meta.get("started_at", "")
    usage = meta.get("usage") or {}

    try:
        file_mtime = os.path.getmtime(filepath)
    except OSError:
        file_mtime = 0.0

    if stop_reason == "in_progress" and file_mtime:
        if (time.time() - file_mtime) > _STALE_THRESHOLD_SECONDS:
            _mark_trace_crashed(filepath)
            stop_reason = "crashed"

    summary = {
        "filename": filename,
        "agent_name": meta.get("agent_name", ""),
        "model": meta.get("model", ""),
        "started_at": started_at,
        "stop_reason": stop_reason,
        "is_active": stop_reason == "in_progress",
        "total_turns": meta.get("total_turns", 0),
        "total_tokens": {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
        },
        "duration_seconds": _compute_duration(started_at, stop_reason, filepath),
        "violation_count": meta.get("violation_count", 0),
        "file_mtime": file_mtime,
    }
    run_id = meta.get("run_id")
    if run_id:
        summary["run_id"] = run_id
    run_sequence = meta.get("run_sequence")
    if run_sequence is not None:
        summary["run_sequence"] = run_sequence
    return summary


def _read_meta_sidecar(meta_fp: str) -> Optional[Dict[str, Any]]:
    """Try to read a ``.meta.json`` sidecar file."""
    try:
        with open(meta_fp, "r", encoding="utf-8") as fh:
            meta = json.load(fh)
        if isinstance(meta, dict) and "agent_name" in meta:
            return meta
    except (OSError, json.JSONDecodeError):
        pass
    return None


def _parse_full_trace_for_summary(
    filepath: str, filename: str
) -> Optional[Dict[str, Any]]:
    """Parse the full trace JSON and return summary-shaped metadata."""
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("Skipping invalid trace file %s: %s", filename, exc)
        return None

    if not isinstance(doc, dict) or "agent_name" not in doc:
        return None

    trace = doc.get("trace") or []
    meta = {
        "agent_name": doc.get("agent_name", ""),
        "model": doc.get("model", ""),
        "started_at": doc.get("started_at", ""),
        "stop_reason": doc.get("stop_reason"),
        "usage": doc.get("usage") or {},
        "total_turns": len(trace),
        "violation_count": _count_violations(trace),
    }
    run_id = doc.get("run_id")
    if run_id:
        meta["run_id"] = run_id
    run_sequence = doc.get("run_sequence")
    if run_sequence is not None:
        meta["run_sequence"] = run_sequence
    return meta


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

    if stop_reason == "in_progress":
        try:
            file_mtime = os.path.getmtime(filepath)
            if (time.time() - file_mtime) > _STALE_THRESHOLD_SECONDS:
                _mark_trace_crashed(filepath)
                stop_reason = "crashed"
                doc["stop_reason"] = "crashed"
        except OSError:
            pass

    computed = compute_token_summary(trace, usage, model)
    computed["duration_seconds"] = _compute_duration(started_at, stop_reason, filepath)

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

    computed["violation_count"] = _count_violations(trace)
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


def group_traces_by_run(traces: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group traces sharing a ``run_id`` into aggregate run entries.

    Returns a mixed list of run-group dicts (``type="run_group"``) and
    standalone trace dicts (no ``run_id``).  Sorted by ``started_at``
    descending.
    """
    groups: Dict[str, List[Dict[str, Any]]] = {}
    standalone: List[Dict[str, Any]] = []

    for t in traces:
        rid = t.get("run_id")
        if rid:
            groups.setdefault(rid, []).append(t)
        else:
            standalone.append(t)

    result: List[Dict[str, Any]] = list(standalone)

    for rid, members in groups.items():
        if len(members) == 1:
            result.append(members[0])
            continue
        members.sort(key=lambda m: m.get("started_at", ""))
        total_violations = sum(m.get("violation_count", 0) for m in members)
        earliest = min((m.get("started_at") or "" for m in members), default="")
        total_duration = sum(m.get("duration_seconds", 0) for m in members)
        is_active = any(m.get("is_active", False) for m in members)
        result.append(
            {
                "type": "run_group",
                "run_id": rid,
                "agent_count": len(members),
                "traces": members,
                "total_duration": total_duration,
                "total_violations": total_violations,
                "started_at": earliest,
                "is_active": is_active,
            }
        )

    result.sort(key=lambda t: t.get("started_at", ""), reverse=True)
    return result


def _compute_duration(
    started_at: str,
    stop_reason: str = "",
    filepath: str = "",
) -> float:
    """Compute duration from started_at to end time.

    For active traces (stop_reason == "in_progress"), end time is now.
    For completed traces, end time is the file modification time.
    Falls back to now if no filepath is available.
    """
    if not started_at:
        return 0.0
    try:
        start_dt = datetime.fromisoformat(started_at)
        from datetime import timezone

        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)

        if stop_reason == "in_progress":
            end_dt = datetime.now(timezone.utc)
        elif filepath:
            try:
                mtime = os.path.getmtime(filepath)
                end_dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
            except OSError:
                end_dt = datetime.now(timezone.utc)
        else:
            end_dt = datetime.now(timezone.utc)
        return max(0.0, (end_dt - start_dt).total_seconds())
    except (ValueError, TypeError):
        return 0.0


def pushed_trace_to_summary(filename: str, doc: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a pushed trace document to a list summary dict."""
    usage = doc.get("usage") or {}
    trace = doc.get("trace") or []
    stop_reason = doc.get("stop_reason")

    violation_count = _count_violations(trace)

    summary = {
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
        "duration_seconds": _compute_duration(doc.get("started_at", ""), stop_reason),
        "violation_count": violation_count,
        "file_mtime": 0.0,
    }
    run_id = doc.get("run_id")
    if run_id:
        summary["run_id"] = run_id
    run_sequence = doc.get("run_sequence")
    if run_sequence is not None:
        summary["run_sequence"] = run_sequence
    return summary
