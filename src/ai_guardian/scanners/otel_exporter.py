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
         ├─ gen_ai.security_scan  — security scan
         └─ gen_ai.compaction  — context compaction
"""

import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

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
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        epoch_s = dt.timestamp()
        return str(int(epoch_s * 1_000_000_000))
    except (ValueError, TypeError):
        return "0"


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
    Steps without timing data become zero-duration markers at *turn_start*.
    """
    start = _iso_to_unix_nano(turn_start)
    latency = step.get("latency_ms")
    if latency is not None:
        end = str(int(start) + latency * 1_000_000)
    else:
        end = start
    return start, end


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
                    ("tool.latency_ms", step.get("latency_ms")),
                ),
            )
        )

    elif step_type == "scan":
        violations = step.get("violations", [])
        violation_types = [v.get("type", "") for v in violations] if violations else []
        violation_ids = [v.get("id") for v in violations if v.get("id")]
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
                    ("gen_ai.security_scan.violation_count", len(violations)),
                    ("gen_ai.security_scan.violation_types", violation_types or None),
                    ("gen_ai.security_scan.violation_ids", violation_ids or None),
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

    turn_span = _make_span(
        trace_id=trace_id,
        span_id=turn_span_id,
        parent_span_id=root_span_id,
        name="gen_ai.turn",
        start_nano=_iso_to_unix_nano(turn_start),
        end_nano=_iso_to_unix_nano(turn_end),
        attributes=_attrs(
            ("gen_ai.turn.number", turn.get("turn")),
            (
                "gen_ai.turn.messages_count",
                input_step.get("messages_count") if input_step else None,
            ),
            (
                "gen_ai.turn.compacted",
                input_step.get("compacted") if input_step else None,
            ),
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
) -> Dict[str, Any]:
    """Create the root gen_ai.agent span from the trace document."""
    parent_span_id_raw = ""
    turns = trace_doc.get("trace", [])
    if turns:
        parent_span_id_raw = turns[0].get("parent_span_id", "")

    root_span_id = (
        _truncate_span_id(parent_span_id_raw) if parent_span_id_raw else _new_span_id()
    )

    usage = trace_doc.get("usage") or {}
    stop_reason = trace_doc.get("stop_reason", "")
    status_code = _STATUS_CODE_ERROR if stop_reason == "error" else _STATUS_CODE_OK

    return _make_span(
        trace_id=trace_id,
        span_id=root_span_id,
        parent_span_id="",
        name="gen_ai.agent",
        start_nano=_iso_to_unix_nano(trace_doc.get("started_at", "")),
        end_nano=_iso_to_unix_nano(trace_doc.get("ended_at", "")),
        attributes=_attrs(
            ("gen_ai.system", "anthropic"),
            ("gen_ai.agent.name", trace_doc.get("agent_name")),
            ("gen_ai.request.model", trace_doc.get("model")),
            ("gen_ai.request.max_tokens", trace_doc.get("max_tokens")),
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
            ("gen_ai.agent.stop_reason", stop_reason),
            ("gen_ai.agent.duration_ms", trace_doc.get("duration_ms")),
        ),
        status_code=status_code,
    )


def trace_to_otlp_json(
    trace_doc: Dict[str, Any],
    *,
    service_name: str = "ai-guardian-sdk",
) -> Dict[str, Any]:
    """Convert an ai-guardian trace document to OTLP JSON format.

    Parameters
    ----------
    trace_doc:
        A parsed ai-guardian trace JSON document (the full dict).
    service_name:
        The ``service.name`` resource attribute.

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
    for turn in turns:
        all_spans.extend(_make_turn_span(turn, trace_id, root_span_id))

    try:
        from ai_guardian import __version__

        version = __version__
    except Exception:
        version = "unknown"

    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": _attrs(
                        ("service.name", service_name),
                        ("service.version", version),
                    )
                },
                "scopeSpans": [
                    {
                        "scope": {
                            "name": "ai-guardian-sdk",
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

    service_name = getattr(args, "service_name", "ai-guardian-sdk")
    otlp = trace_to_otlp_json(trace_doc, service_name=service_name)

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
    service_name = getattr(args, "service_name", "ai-guardian-sdk")
    count = 0

    for entry in sorted(os.listdir(trace_dir)):
        if not entry.endswith(".json"):
            continue
        src = os.path.join(trace_dir, entry)
        try:
            with open(src, "r", encoding="utf-8") as fh:
                trace_doc = json.load(fh)
            otlp = trace_to_otlp_json(trace_doc, service_name=service_name)
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
    ) -> None:
        self._enabled = config.get("enabled", False)
        if not self._enabled:
            return
        self._endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or config.get(
            "endpoint", "http://localhost:4318"
        )
        self._service_name = os.environ.get("OTEL_SERVICE_NAME") or config.get(
            "service_name", "ai-guardian-sdk"
        )
        self._format = config.get("export_format", "otlp-json")
        self._headers = _resolve_headers(config.get("headers"))
        self._trace_id = trace_id
        self._agent_name = agent_name
        self._model = model

    def on_turn_complete(self, turn_data: Dict[str, Any]) -> None:
        """Called after a turn finishes.  Converts to spans and flushes."""
        if not self._enabled:
            return
        try:
            root_span_id = _truncate_span_id(
                turn_data.get("parent_span_id", _new_span_id())
            )
            spans = _make_turn_span(turn_data, self._trace_id, root_span_id)
            self._flush(spans)
        except Exception:
            logger.debug("OTEL turn export failed", exc_info=True)

    def on_run_complete(self, trace_doc: Dict[str, Any]) -> None:
        """Called after the full run finishes.  Sends the root span."""
        if not self._enabled:
            return
        try:
            root = _make_root_span(trace_doc, self._trace_id)
            self._flush([root])
        except Exception:
            logger.debug("OTEL run export failed", exc_info=True)

    def _flush(self, spans: List[Dict[str, Any]]) -> None:
        """POST spans to the OTEL collector.  Fire-and-forget."""

        try:
            from ai_guardian import __version__

            version = __version__
        except Exception:
            version = "unknown"

        payload = {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": _attrs(
                            ("service.name", self._service_name),
                            ("service.version", version),
                        )
                    },
                    "scopeSpans": [
                        {
                            "scope": {
                                "name": "ai-guardian-sdk",
                                "version": version,
                            },
                            "spans": spans,
                        }
                    ],
                }
            ]
        }

        url = self._endpoint.rstrip("/") + "/v1/traces"
        try:
            hdrs = {"Content-Type": "application/json"}
            hdrs.update(self._headers)
            requests.post(
                url,
                json=payload,
                headers=hdrs,
                timeout=5,
            )
        except Exception:
            logger.debug("OTEL flush to %s failed", url, exc_info=True)
