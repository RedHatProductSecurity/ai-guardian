"""Convert ai-guardian agent traces to OTLP JSON (OpenTelemetry GenAI format).

Produces valid OTLP JSON (ResourceSpans -> ScopeSpans -> Spans) without any
``opentelemetry-*`` dependency.  The optional ``opentelemetry-*`` packages are
only needed for protobuf serialization and live TracerProvider integration.

ID mapping:
  - trace_id (32 hex chars) passes through unchanged — matches OTEL spec.
  - span_id is truncated from 32 hex chars (uuid4) to 16 hex chars (64-bit)
    per OTEL spec.  UUID4 has sufficient entropy in all positions.

Span hierarchy:
  Root (gen_ai.agent)  — one per agent run
    └─ Turn (gen_ai.turn)  — one per conversation turn
         ├─ gen_ai.chat  — LLM response
         ├─ tool  — tool_call / tool_result
         ├─ gen_ai.security_scan  — security scan (target only)
         └─ gen_ai.compaction  — context compaction
"""

import json
import logging
import os
import platform
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_SPAN_KIND_INTERNAL = 1
_STATUS_CODE_OK = 1
_STATUS_CODE_ERROR = 2


def _truncate_span_id(hex_32: str) -> str:
    """Truncate a 32-char hex UUID to 16-char OTEL span_id."""
    return hex_32[:16]


def _new_span_id() -> str:
    """Generate a fresh 16-char hex span ID."""
    return uuid.uuid4().hex[:16]


def _iso_to_unix_nano(iso_str: str) -> str:
    """Convert an ISO 8601 timestamp string to Unix nanoseconds string.

    Returns ``"0"`` if *iso_str* is ``None`` or unparseable.
    """
    if not iso_str:
        return "0"
    try:
        from ai_guardian.config.utils import parse_iso8601

        dt = parse_iso8601(iso_str)
        if dt is None:
            return "0"
        epoch_s = dt.timestamp()
        return str(int(epoch_s * 1_000_000_000))
    except (ValueError, TypeError):
        return "0"


def _derive_end_nano(
    iso_str: str,
    start_nano: str,
    *,
    duration_ms: Optional[int] = None,
    output_tokens: Optional[int] = None,
) -> str:
    """Compute end time nanoseconds, synthesizing when the source is missing.

    Falls back to *start_nano* + *duration_ms*, token-based estimate,
    or a 1 ms synthetic minimum — in that priority order.
    """
    end = _iso_to_unix_nano(iso_str)
    if end != "0":
        return end
    if start_nano == "0":
        return "0"
    start_int = int(start_nano)
    if duration_ms is not None and duration_ms > 0:
        return str(start_int + int(duration_ms * 1_000_000))
    if output_tokens is not None and output_tokens > 0:
        estimated_ms = max(1, (output_tokens / 30) * 1000)
        return str(start_int + int(estimated_ms * 1_000_000))
    return str(start_int + 1_000_000)


def _make_attribute(key: str, value: Any) -> Optional[Dict[str, Any]]:
    """Create a single OTLP attribute dict with a typed value.

    Returns ``None`` for unsupported or ``None`` values.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    if isinstance(value, float):
        return {"key": key, "value": {"intValue": str(int(value))}}
    if isinstance(value, str):
        return {"key": key, "value": {"stringValue": value}}
    if isinstance(value, list):
        str_vals = [{"stringValue": str(v)} for v in value]
        return {"key": key, "value": {"arrayValue": {"values": str_vals}}}
    return {"key": key, "value": {"stringValue": str(value)}}


def _attrs(*pairs) -> List[Dict[str, Any]]:
    """Build an attribute list from ``(key, value)`` pairs, skipping Nones."""
    result = []
    for key, value in pairs:
        attr = _make_attribute(key, value)
        if attr is not None:
            result.append(attr)
    return result


def _make_span(
    *,
    trace_id: str,
    span_id: str,
    parent_span_id: str,
    name: str,
    start_nano: str,
    end_nano: str,
    attributes: List[Dict[str, Any]],
    status_code: int = _STATUS_CODE_OK,
    kind: int = _SPAN_KIND_INTERNAL,
) -> Dict[str, Any]:
    """Build a single OTLP Span dict."""
    if end_nano == "0" and start_nano != "0":
        end_nano = str(int(start_nano) + 1_000_000)
    span: Dict[str, Any] = {
        "traceId": trace_id,
        "spanId": span_id,
        "name": name,
        "kind": kind,
        "startTimeUnixNano": start_nano,
        "endTimeUnixNano": end_nano,
        "attributes": attributes,
        "status": {"code": status_code},
    }
    if parent_span_id:
        span["parentSpanId"] = parent_span_id
    return span


def _step_timing(step: Dict[str, Any], turn_start: str, turn_end: str):
    """Derive start/end nanoseconds for a step.

    Steps with ``latency_ms`` get that duration anchored at *turn_start*.
    Steps without timing synthesize from output tokens (~30 tok/sec) or 1 ms.
    """
    start = _iso_to_unix_nano(turn_start)
    if start == "0":
        return "0", "0"
    latency = step.get("latency_ms")
    if latency is not None:
        return start, str(int(start) + int(latency * 1_000_000))
    usage = step.get("usage", {})
    output_tokens = usage.get("output_tokens")
    if output_tokens and output_tokens > 0:
        estimated_ms = max(1, (output_tokens / 30) * 1000)
        return start, str(int(start) + int(estimated_ms * 1_000_000))
    return start, str(int(start) + 1_000_000)


def _make_step_spans(
    step: Dict[str, Any],
    trace_id: str,
    parent_span_id: str,
    turn_start: str,
    turn_end: str,
) -> List[Dict[str, Any]]:
    """Convert a single trace step dict into one or more OTEL spans."""
    step_type = step.get("type", "")
    start, end = _step_timing(step, turn_start, turn_end)
    spans: List[Dict[str, Any]] = []

    if step_type == "response":
        usage = step.get("usage", {})
        text = step.get("text")
        text_length = step.get("text_length")
        if text_length is None and text:
            text_length = len(text)
        spans.append(
            _make_span(
                trace_id=trace_id,
                span_id=_new_span_id(),
                parent_span_id=parent_span_id,
                name="gen_ai.chat",
                start_nano=start,
                end_nano=end,
                attributes=_attrs(
                    ("gen_ai.response.finish_reasons", [step.get("model_signal", "")]),
                    ("gen_ai.usage.input_tokens", usage.get("input_tokens")),
                    ("gen_ai.usage.output_tokens", usage.get("output_tokens")),
                    (
                        "gen_ai.usage.cache_read_input_tokens",
                        usage.get("cache_read_input_tokens"),
                    ),
                    (
                        "gen_ai.usage.cache_creation_input_tokens",
                        usage.get("cache_creation_input_tokens"),
                    ),
                    ("gen_ai.chat.latency_ms", step.get("latency_ms")),
                    ("gen_ai.response.text_length", text_length),
                    ("gen_ai.response.tool_call_count", step.get("tool_call_count")),
                ),
            )
        )

    elif step_type == "tool_call":
        tool_input = step.get("input")
        input_str = json.dumps(tool_input)[:1024] if tool_input else None
        spans.append(
            _make_span(
                trace_id=trace_id,
                span_id=_new_span_id(),
                parent_span_id=parent_span_id,
                name=f"tool:{step.get('name', 'unknown')}",
                start_nano=start,
                end_nano=end,
                attributes=_attrs(
                    ("tool.name", step.get("name")),
                    ("tool.input", input_str),
                ),
            )
        )

    elif step_type == "tool_result":
        spans.append(
            _make_span(
                trace_id=trace_id,
                span_id=_new_span_id(),
                parent_span_id=parent_span_id,
                name=f"tool_result:{step.get('name', 'unknown')}",
                start_nano=start,
                end_nano=end,
                attributes=_attrs(
                    ("tool.name", step.get("name")),
                    ("tool.output_bytes", step.get("output_bytes")),
                    ("tool.output_truncated", step.get("output_truncated")),
                    ("tool.latency_ms", step.get("latency_ms")),
                ),
            )
        )

    elif step_type == "scan":
        spans.append(
            _make_span(
                trace_id=trace_id,
                span_id=_new_span_id(),
                parent_span_id=parent_span_id,
                name="gen_ai.security_scan",
                start_nano=start,
                end_nano=end,
                attributes=_attrs(
                    ("gen_ai.security_scan.target", step.get("scanned")),
                ),
            )
        )

    elif step_type == "compaction":
        spans.append(
            _make_span(
                trace_id=trace_id,
                span_id=_new_span_id(),
                parent_span_id=parent_span_id,
                name="gen_ai.compaction",
                start_nano=start,
                end_nano=end,
                attributes=_attrs(
                    ("gen_ai.compaction.tokens_before", step.get("tokens_before")),
                    ("gen_ai.compaction.tokens_after", step.get("tokens_after")),
                    ("gen_ai.compaction.method", step.get("method")),
                ),
            )
        )

    return spans


def _make_turn_span(
    turn: Dict[str, Any],
    trace_id: str,
    root_span_id: str,
    *,
    prev_messages_count: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Convert a turn object into a turn span plus child step spans."""
    turn_span_id = _truncate_span_id(turn.get("span_id", _new_span_id()))
    turn_start = turn.get("started_at", "")
    turn_end = turn.get("ended_at", "")

    input_step = None
    for s in turn.get("steps", []):
        if s.get("type") == "input":
            input_step = s
            break

    messages_count = input_step.get("messages_count") if input_step else None
    messages_count_growth = None
    if messages_count is not None and prev_messages_count is not None:
        messages_count_growth = messages_count - prev_messages_count

    start_nano = _iso_to_unix_nano(turn_start)
    end_nano = _derive_end_nano(
        turn_end,
        start_nano,
        duration_ms=turn.get("duration_ms"),
    )

    turn_span = _make_span(
        trace_id=trace_id,
        span_id=turn_span_id,
        parent_span_id=root_span_id,
        name="gen_ai.turn",
        start_nano=start_nano,
        end_nano=end_nano,
        attributes=_attrs(
            ("gen_ai.turn.number", turn.get("turn")),
            ("gen_ai.turn.messages_count", messages_count),
            (
                "gen_ai.turn.compacted",
                input_step.get("compacted") if input_step else None,
            ),
            ("gen_ai.turn.messages_count_growth", messages_count_growth),
            ("gen_ai.turn.duration_ms", turn.get("duration_ms")),
        ),
    )

    spans = [turn_span]
    for step in turn.get("steps", []):
        if step.get("type") in ("system", "input"):
            continue
        spans.extend(
            _make_step_spans(step, trace_id, turn_span_id, turn_start, turn_end)
        )

    return spans


def _make_root_span(
    trace_doc: Dict[str, Any],
    trace_id: str,
    *,
    root_span_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create the root gen_ai.agent span from the trace document."""
    if root_span_id is None:
        parent_span_id_raw = ""
        turns = trace_doc.get("trace", [])
        if turns:
            parent_span_id_raw = turns[0].get("parent_span_id", "")

        root_span_id = (
            _truncate_span_id(parent_span_id_raw)
            if parent_span_id_raw
            else _new_span_id()
        )

    usage = trace_doc.get("usage") or {}
    stop_reason = trace_doc.get("stop_reason", "")
    status_code = _STATUS_CODE_ERROR if stop_reason == "error" else _STATUS_CODE_OK

    start_nano = _iso_to_unix_nano(trace_doc.get("started_at", ""))
    if start_nano == "0" and turns:
        start_nano = _iso_to_unix_nano(turns[0].get("started_at", ""))

    end_iso = trace_doc.get("ended_at", "")
    if not end_iso and turns:
        end_iso = turns[-1].get("ended_at", "")

    end_nano = _derive_end_nano(
        end_iso,
        start_nano,
        duration_ms=trace_doc.get("duration_ms"),
        output_tokens=usage.get("output_tokens"),
    )

    root_attrs_pairs = [
        ("gen_ai.system", "anthropic"),
        ("gen_ai.agent.name", trace_doc.get("agent_name")),
        ("gen_ai.request.model", trace_doc.get("model")),
        ("gen_ai.request.max_tokens", trace_doc.get("max_tokens")),
        ("gen_ai.agent.stop_reason", stop_reason),
        ("gen_ai.agent.duration_ms", trace_doc.get("duration_ms")),
        ("gen_ai.agent.hostname", platform.node() or None),
        ("ai_guardian.session_id", trace_doc.get("session_id")),
        ("ai_guardian.project.name", trace_doc.get("project_name")),
        ("ai_guardian.run_id", trace_doc.get("run_id")),
        ("ai_guardian.run_sequence", trace_doc.get("run_sequence")),
    ]
    run_metadata = trace_doc.get("run_metadata")
    if run_metadata and isinstance(run_metadata, dict):
        for k, v in run_metadata.items():
            root_attrs_pairs.append((f"ai_guardian.meta.{k}", v))

    return _make_span(
        trace_id=trace_id,
        span_id=root_span_id,
        parent_span_id="",
        name="gen_ai.agent",
        start_nano=start_nano,
        end_nano=end_nano,
        attributes=_attrs(*root_attrs_pairs),
        status_code=status_code,
    )


def trace_to_otlp_json(
    trace_doc: Dict[str, Any],
    *,
    service_name: str = "ai-guardian",
    resource_attributes: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Convert an ai-guardian trace document to OTLP JSON format.

    Parameters
    ----------
    trace_doc:
        A parsed ai-guardian trace JSON document (the full dict).
    service_name:
        The ``service.name`` resource attribute.
    resource_attributes:
        Static key-value pairs added as OTEL resource attributes.

    Returns
    -------
    dict
        An OTLP JSON dict ready for ``json.dumps()`` or POST to a collector.
    """
    trace_id = trace_doc.get("trace_id", uuid.uuid4().hex)
    turns = trace_doc.get("trace", [])

    root_span = _make_root_span(trace_doc, trace_id)
    root_span_id = root_span["spanId"]

    all_spans = [root_span]
    prev_messages_count = None
    for turn in turns:
        all_spans.extend(
            _make_turn_span(
                turn, trace_id, root_span_id, prev_messages_count=prev_messages_count
            )
        )
        input_step = next(
            (s for s in turn.get("steps", []) if s.get("type") == "input"), None
        )
        if input_step and input_step.get("messages_count") is not None:
            prev_messages_count = input_step["messages_count"]

    try:
        from ai_guardian import __version__

        version = __version__
    except Exception:
        version = "unknown"

    res_attrs = _attrs(
        ("service.name", service_name),
        ("service.version", version),
    )
    if resource_attributes:
        for key, value in resource_attributes.items():
            attr = _make_attribute(key, value)
            if attr is not None:
                res_attrs.append(attr)

    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": res_attrs,
                },
                "scopeSpans": [
                    {
                        "scope": {
                            "name": "ai-guardian",
                            "version": version,
                        },
                        "spans": all_spans,
                    }
                ],
            }
        ]
    }


# ---------------------------------------------------------------------------
# CLI handler
# ---------------------------------------------------------------------------


def _export_single(args) -> int:
    """Handle ``ai-guardian trace export <file>``."""

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"Error: file not found: {filepath}", file=sys.stderr)
        return 1

    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            trace_doc = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Error: failed to read trace file: {exc}", file=sys.stderr)
        return 1

    service_name = getattr(args, "service_name", "ai-guardian")

    resource_attributes = None
    try:
        from ai_guardian.config.loaders import _load_otel_config

        resource_attributes = _load_otel_config().get("resource_attributes")
    except Exception:
        pass

    otlp = trace_to_otlp_json(
        trace_doc, service_name=service_name, resource_attributes=resource_attributes
    )

    fmt = getattr(args, "format", "otlp-json")
    endpoint = getattr(args, "endpoint", None)

    if endpoint:
        url = endpoint.rstrip("/") + "/v1/traces"
        try:
            hdrs = {"Content-Type": "application/json"}
            for h in getattr(args, "headers", None) or []:
                if "=" in h:
                    k, v = h.split("=", 1)
                    hdrs[k.strip()] = v.strip()
            resp = requests.post(
                url,
                json=otlp,
                headers=hdrs,
                timeout=30,
            )
            resp.raise_for_status()
            print(f"Exported to {url} (HTTP {resp.status_code})")
            return 0
        except Exception as exc:
            print(f"Error: failed to send to collector: {exc}", file=sys.stderr)
            return 1

    if fmt == "otlp-proto":
        try:
            data = _to_protobuf(otlp)
        except ImportError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        output = getattr(args, "output", None)
        if output:
            with open(output, "wb") as fh:
                fh.write(data)
            print(f"Exported protobuf to {output}")
        else:
            sys.stdout.buffer.write(data)
        return 0

    output_json = json.dumps(otlp, indent=2)
    output = getattr(args, "output", None)
    if output:
        with open(output, "w", encoding="utf-8") as fh:
            fh.write(output_json)
        print(f"Exported OTLP JSON to {output}")
    else:
        print(output_json)
    return 0


def _export_dir(args) -> int:
    """Handle ``ai-guardian trace export-dir [dir]``."""
    from ai_guardian.daemon.traces import resolve_trace_dirs

    trace_dir = getattr(args, "dir", None)
    if not trace_dir:
        dirs = resolve_trace_dirs()
        if not dirs:
            print("Error: no trace directory found", file=sys.stderr)
            return 1
        trace_dir = dirs[0]

    if not os.path.isdir(trace_dir):
        print(f"Error: directory not found: {trace_dir}", file=sys.stderr)
        return 1

    output_dir = getattr(args, "output", None)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    fmt = getattr(args, "format", "otlp-json")
    service_name = getattr(args, "service_name", "ai-guardian")

    resource_attributes = None
    try:
        from ai_guardian.config.loaders import _load_otel_config

        resource_attributes = _load_otel_config().get("resource_attributes")
    except Exception:
        pass

    count = 0

    for entry in sorted(os.listdir(trace_dir)):
        if not entry.endswith(".json"):
            continue
        src = os.path.join(trace_dir, entry)
        try:
            with open(src, "r", encoding="utf-8") as fh:
                trace_doc = json.load(fh)
            otlp = trace_to_otlp_json(
                trace_doc,
                service_name=service_name,
                resource_attributes=resource_attributes,
            )
        except Exception as exc:
            print(f"Warning: skipping {entry}: {exc}", file=sys.stderr)
            continue

        if fmt == "otlp-proto":
            try:
                data = _to_protobuf(otlp)
            except ImportError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            ext = ".pb"
        else:
            data = json.dumps(otlp, indent=2).encode("utf-8")
            ext = ".otlp.json"

        out_name = entry.rsplit(".", 1)[0] + ext
        if output_dir:
            out_path = os.path.join(output_dir, out_name)
            mode = "wb" if isinstance(data, bytes) else "w"
            with open(out_path, mode) as fh:
                fh.write(data)
        else:
            if isinstance(data, bytes):
                sys.stdout.buffer.write(data)
            else:
                print(data)
        count += 1

    print(f"Exported {count} trace(s)", file=sys.stderr)
    return 0


def _to_protobuf(otlp_json: Dict[str, Any]) -> bytes:
    """Serialize OTLP JSON to protobuf bytes.

    Raises ``ImportError`` if the required packages are not installed.
    """
    try:
        from google.protobuf.json_format import ParseDict
        from opentelemetry.proto.collector.trace.v1 import (
            trace_service_pb2,
        )
    except ImportError:
        raise ImportError(
            "Protobuf export requires OTEL dependencies: "
            "pip install ai-guardian[otel]"
        )
    msg = ParseDict(otlp_json, trace_service_pb2.ExportTraceServiceRequest())
    return msg.SerializeToString()


def handle_trace_command(args, parser) -> int:
    """Dispatch ``ai-guardian trace`` subcommands."""
    trace_cmd = getattr(args, "trace_command", None)
    if trace_cmd == "export":
        return _export_single(args)
    if trace_cmd == "export-dir":
        return _export_dir(args)
    parser.print_help()
    return 0


# ---------------------------------------------------------------------------
# Live OTEL export — OtelSpanEmitter
# ---------------------------------------------------------------------------


def _resolve_headers(config_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Merge OTEL headers from config and ``OTEL_EXPORTER_OTLP_HEADERS`` env var.

    The env var follows the OTEL spec format: ``key1=val1,key2=val2``.
    Config headers take precedence over env var headers.
    """
    headers: Dict[str, str] = {}
    env_val = os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", "")
    if env_val:
        for pair in env_val.split(","):
            pair = pair.strip()
            if "=" in pair:
                k, v = pair.split("=", 1)
                headers[k.strip()] = v.strip()
    if config_headers and isinstance(config_headers, dict):
        headers.update(config_headers)
    return headers


class _OtelConfig:
    """Shared OTEL configuration resolved from config dict and environment."""

    __slots__ = (
        "enabled",
        "endpoint",
        "service_name",
        "headers",
        "resource_attributes",
    )

    def __init__(self, config: Dict[str, Any]) -> None:
        self.enabled: bool = config.get("enabled", False)
        if not self.enabled:
            return
        self.endpoint: str = os.environ.get(
            "OTEL_EXPORTER_OTLP_ENDPOINT"
        ) or config.get("endpoint", "http://localhost:4318")
        self.service_name: str = os.environ.get("OTEL_SERVICE_NAME") or config.get(
            "service_name", "ai-guardian"
        )
        self.headers: Dict[str, str] = _resolve_headers(config.get("headers"))
        self.resource_attributes: Dict[str, Any] = (
            config.get("resource_attributes") or {}
        )


def _post_otel_spans(
    cfg: _OtelConfig,
    spans: List[Dict[str, Any]],
) -> None:
    """POST spans to an OTEL collector. Fire-and-forget."""
    try:
        from ai_guardian import __version__

        version = __version__
    except Exception:
        version = "unknown"

    res_attrs = _attrs(
        ("service.name", cfg.service_name),
        ("service.version", version),
    )
    for key, value in cfg.resource_attributes.items():
        attr = _make_attribute(key, value)
        if attr is not None:
            res_attrs.append(attr)

    payload = {
        "resourceSpans": [
            {
                "resource": {"attributes": res_attrs},
                "scopeSpans": [
                    {
                        "scope": {
                            "name": "ai-guardian",
                            "version": version,
                        },
                        "spans": spans,
                    }
                ],
            }
        ]
    }

    url = cfg.endpoint.rstrip("/") + "/v1/traces"
    try:
        hdrs = {"Content-Type": "application/json"}
        hdrs.update(cfg.headers)
        requests.post(url, json=payload, headers=hdrs, timeout=5)
    except Exception:
        logger.debug("OTEL flush to %s failed", url, exc_info=True)


class OtelSpanEmitter:
    """Emit OTEL spans to a collector during an agent run.

    Instantiated once per run.  When ``enabled`` is ``False`` (the default),
    all methods are no-ops — no network calls, no imports.
    """

    def __init__(
        self,
        config: Dict[str, Any],
        trace_id: str,
        agent_name: str,
        model: str,
        metadata_fn: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None,
        run_id: Optional[str] = None,
        run_sequence: Optional[int] = None,
        run_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._cfg = _OtelConfig(config)
        self._enabled = self._cfg.enabled
        self._metadata_fn = metadata_fn
        self._root_span_id: Optional[str] = None
        self._run_id = run_id
        self._run_sequence = run_sequence
        self._run_metadata = run_metadata or {}
        if not self._enabled:
            return
        self._trace_id = trace_id
        self._agent_name = agent_name
        self._model = model
        self._prev_messages_count: Optional[int] = None

    def _call_metadata_fn(
        self,
        turn: int,
        usage: Optional[Dict[str, Any]] = None,
        stop_reason: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Call the metadata callback and return OTLP attributes."""
        if not self._metadata_fn:
            return []
        try:
            ctx: Dict[str, Any] = {
                "model": self._model,
                "turn": turn,
                "usage": usage or {},
            }
            if stop_reason is not None:
                ctx["stop_reason"] = stop_reason
            result = self._metadata_fn(self._agent_name, ctx)
            if not isinstance(result, dict):
                return []
            return _attrs(*result.items())
        except Exception:
            logger.debug("OTEL metadata_fn failed", exc_info=True)
            return []

    def on_run_start(
        self,
        *,
        started_at: str,
        parent_span_id: str,
    ) -> None:
        """Send initial root span at agent start so traces are visible immediately."""
        if not self._enabled:
            return
        try:
            self._root_span_id = _truncate_span_id(parent_span_id)
            start_nano = _iso_to_unix_nano(started_at)
            end_nano = str(int(start_nano) + 1_000_000) if start_nano != "0" else "0"

            run_attrs = []
            if self._run_id:
                run_attrs.append(("ai_guardian.run_id", self._run_id))
            if self._run_sequence is not None:
                run_attrs.append(("ai_guardian.run_sequence", self._run_sequence))
            for k, v in self._run_metadata.items():
                run_attrs.append((f"ai_guardian.meta.{k}", v))

            root = _make_span(
                trace_id=self._trace_id,
                span_id=self._root_span_id,
                parent_span_id="",
                name="gen_ai.agent",
                start_nano=start_nano,
                end_nano=end_nano,
                attributes=_attrs(
                    ("gen_ai.system", "anthropic"),
                    ("gen_ai.agent.name", self._agent_name),
                    ("gen_ai.request.model", self._model),
                    ("gen_ai.agent.stop_reason", "in_progress"),
                    ("ai_guardian.span_type", "agent_run"),
                    *run_attrs,
                ),
            )
            dynamic_attrs = self._call_metadata_fn(turn=0)
            if dynamic_attrs:
                root["attributes"].extend(dynamic_attrs)
            self._flush([root])
        except Exception:
            logger.debug("OTEL run start emit failed", exc_info=True)

    def on_turn_complete(
        self,
        turn_data: Dict[str, Any],
        *,
        usage_totals: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Called after a turn finishes.  Converts to spans and flushes."""
        if not self._enabled:
            return
        try:
            root_span_id = self._root_span_id or _truncate_span_id(
                turn_data.get("parent_span_id", _new_span_id())
            )
            spans = _make_turn_span(
                turn_data,
                self._trace_id,
                root_span_id,
                prev_messages_count=self._prev_messages_count,
            )
            input_step = next(
                (s for s in turn_data.get("steps", []) if s.get("type") == "input"),
                None,
            )
            if input_step and input_step.get("messages_count") is not None:
                self._prev_messages_count = input_step["messages_count"]
            dynamic_attrs = self._call_metadata_fn(
                turn=turn_data.get("turn", 0),
                usage=usage_totals,
            )
            if dynamic_attrs and spans:
                spans[0]["attributes"].extend(dynamic_attrs)
            self._flush(spans)
        except Exception:
            logger.debug("OTEL turn export failed", exc_info=True)

    def on_run_complete(self, trace_doc: Dict[str, Any]) -> None:
        """Called after the full run finishes.  Sends the root span."""
        if not self._enabled:
            return
        try:
            root = _make_root_span(
                trace_doc, self._trace_id, root_span_id=self._root_span_id
            )
            root["attributes"].extend(_attrs(("ai_guardian.span_type", "agent_run")))
            dynamic_attrs = self._call_metadata_fn(
                turn=0,
                usage=trace_doc.get("usage"),
                stop_reason=trace_doc.get("stop_reason"),
            )
            if dynamic_attrs:
                root["attributes"].extend(dynamic_attrs)
            self._flush([root])
        except Exception:
            logger.debug("OTEL run export failed", exc_info=True)

    def _flush(self, spans: List[Dict[str, Any]]) -> None:
        """POST spans to the OTEL collector.  Fire-and-forget."""
        _post_otel_spans(self._cfg, spans)


def _read_session_violations(
    session_id: str,
    *,
    violations_log_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Read violations from ``violations.jsonl`` filtered by *session_id*.

    Returns a list of violation entry dicts.  Silently returns ``[]`` on
    missing file, I/O errors, or malformed lines.
    """
    if not session_id:
        return []
    if violations_log_path is None:
        try:
            from ai_guardian.config.utils import get_state_dir

            violations_log_path = str(get_state_dir() / "violations.jsonl")
        except Exception:
            return []
    if not os.path.isfile(violations_log_path):
        return []
    entries: List[Dict[str, Any]] = []
    try:
        with open(violations_log_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ctx = entry.get("context") or {}
                if ctx.get("session_id") == session_id:
                    entries.append(entry)
    except OSError:
        pass
    return entries


def _violation_entry_to_span(
    entry: Dict[str, Any],
    trace_id: str,
    parent_span_id: str,
) -> Dict[str, Any]:
    """Convert a single violations.jsonl entry to an OTEL span."""
    blocked = entry.get("blocked") or {}
    ctx = entry.get("context") or {}
    timestamp_nano = _iso_to_unix_nano(entry.get("timestamp", ""))

    action = blocked.get("action", "block")
    if action == "block":
        return _make_span(
            trace_id=trace_id,
            span_id=_new_span_id(),
            parent_span_id=parent_span_id,
            name="ai_guardian.block",
            start_nano=timestamp_nano,
            end_nano=timestamp_nano,
            attributes=_attrs(
                ("tool.name", ctx.get("tool_name")),
                ("ai_guardian.reason", blocked.get("reason")),
                ("ai_guardian.scanner", entry.get("violation_type")),
            ),
        )
    return _make_span(
        trace_id=trace_id,
        span_id=_new_span_id(),
        parent_span_id=parent_span_id,
        name="ai_guardian.violation",
        start_nano=timestamp_nano,
        end_nano=timestamp_nano,
        attributes=_attrs(
            ("ai_guardian.violation_type", entry.get("violation_type")),
            ("ai_guardian.severity", entry.get("severity")),
            ("tool.name", ctx.get("tool_name")),
            ("ai_guardian.violation_id", entry.get("id")),
            ("ai_guardian.scanner", entry.get("violation_type")),
        ),
    )


class HookOtelEmitter:
    """Emit OTEL spans for hook session activity (violations, blocks, scans).

    At ``SessionEnd``, reads violations from ``violations.jsonl`` (filtered
    by ``session_id``) and converts them to OTEL spans.  No in-memory span
    accumulation — works in both daemon and direct mode.

    Span hierarchy::

        ai_guardian.session (root)
        ├── ai_guardian.violation (one per non-blocking violation)
        └── ai_guardian.block (one per blocked event)
    """

    def __init__(
        self,
        config: Dict[str, Any],
        *,
        session_sequence: int = 1,
    ) -> None:
        self._cfg = _OtelConfig(config)
        self._enabled = self._cfg.enabled
        if not self._enabled:
            return
        self._trace_id = uuid.uuid4().hex
        self._root_span_id = _new_span_id()
        self._start_nano = str(int(datetime.now(timezone.utc).timestamp() * 1e9))
        self._adapter_name: Optional[str] = None
        self._project_name: Optional[str] = None
        self._session_sequence = session_sequence

    @property
    def enabled(self) -> bool:
        return self._enabled

    def record_session_start(
        self,
        *,
        adapter_name: Optional[str] = None,
        project_name: Optional[str] = None,
    ) -> None:
        """Record session start metadata.

        Called at session creation so that even clean sessions (no
        violations) produce an OTEL trace with a root span.
        """
        if not self._enabled:
            return
        if adapter_name is not None:
            self._adapter_name = adapter_name
        if project_name is not None:
            self._project_name = project_name

    def flush(
        self,
        *,
        session_id: Optional[str] = None,
        adapter_name: Optional[str] = None,
        token_usage: Optional[Dict[str, Any]] = None,
        violations_log_path: Optional[str] = None,
    ) -> None:
        """Read violations from disk and flush as OTEL spans to the collector."""
        if not self._enabled:
            return
        try:
            end_nano = str(int(datetime.now(timezone.utc).timestamp() * 1e9))

            entries = _read_session_violations(
                session_id or "", violations_log_path=violations_log_path
            )
            child_spans = [
                _violation_entry_to_span(e, self._trace_id, self._root_span_id)
                for e in entries
            ]

            block_count = sum(
                1
                for e in entries
                if (e.get("blocked") or {}).get("action", "block") == "block"
            )
            violation_count = len(entries) - block_count

            effective_adapter = adapter_name or self._adapter_name
            root_attrs = _attrs(
                ("ai_guardian.session_id", session_id),
                ("ai_guardian.session_sequence", self._session_sequence),
                ("ai_guardian.project.name", self._project_name),
                ("ai_guardian.adapter", effective_adapter),
                ("ai_guardian.violation_count", violation_count),
                ("ai_guardian.block_count", block_count),
                ("ai_guardian.span_type", "session"),
            )
            if token_usage and isinstance(token_usage, dict):
                root_attrs.extend(
                    _attrs(
                        (
                            "gen_ai.usage.input_tokens",
                            token_usage.get("input_tokens"),
                        ),
                        (
                            "gen_ai.usage.output_tokens",
                            token_usage.get("output_tokens"),
                        ),
                        (
                            "gen_ai.usage.cache_read_input_tokens",
                            token_usage.get("cache_read_input_tokens"),
                        ),
                        (
                            "gen_ai.usage.cache_creation_input_tokens",
                            token_usage.get("cache_creation_input_tokens"),
                        ),
                    )
                )

            root_span = _make_span(
                trace_id=self._trace_id,
                span_id=self._root_span_id,
                parent_span_id="",
                name="ai_guardian.session",
                start_nano=self._start_nano,
                end_nano=end_nano,
                attributes=root_attrs,
            )

            all_spans = [root_span] + child_spans
            self._post_spans(all_spans)
        except Exception:
            logger.debug("OTEL session flush failed", exc_info=True)

    def _post_spans(self, spans: List[Dict[str, Any]]) -> None:
        """POST spans to the OTEL collector. Fire-and-forget."""
        _post_otel_spans(self._cfg, spans)
