"""Map validated TelemetryPlan to OpenTelemetry SDK export."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from opentelemetry import trace
from opentelemetry._logs import LogRecord, get_logger
from opentelemetry._logs.severity import SeverityNumber
from opentelemetry.context import get_current
from opentelemetry.trace import Span

from .telemetry_ir import TelemetryPlan


def _severity(severity_text: str) -> tuple[str, SeverityNumber]:
    t = (severity_text or "INFO").strip().upper()
    mapping: dict[str, tuple[str, SeverityNumber]] = {
        "TRACE": ("TRACE", SeverityNumber.TRACE),
        "DEBUG": ("DEBUG", SeverityNumber.DEBUG),
        "INFO": ("INFO", SeverityNumber.INFO),
        "WARN": ("WARN", SeverityNumber.WARN),
        "WARNING": ("WARN", SeverityNumber.WARN),
        "ERROR": ("ERROR", SeverityNumber.ERROR),
        "FATAL": ("FATAL", SeverityNumber.FATAL),
        "CRITICAL": ("FATAL", SeverityNumber.FATAL),
    }
    if t in mapping:
        return mapping[t][0], mapping[t][1]
    return "INFO", SeverityNumber.INFO


def _apply_resource_to_span(span: Span, plan: TelemetryPlan) -> None:
    res = plan.resource
    if res is None:
        return
    if res.service_name:
        span.set_attribute("telemetry.ingest.resource.service.name", res.service_name)
    if res.deployment_environment:
        span.set_attribute(
            "telemetry.ingest.resource.deployment.environment",
            res.deployment_environment,
        )
    for key, val in res.extra_attributes.items():
        span.set_attribute(f"telemetry.ingest.resource.attributes.{key}", val)


def _metric_attr_dict(attrs: dict[str, str | int | float | bool]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in attrs.items():
        out[k] = str(v) if not isinstance(v, (int, float, bool)) else v
    return out


@dataclass
class EmitHandles:
    tracer: trace.Tracer
    otel_logger_name: str
    ingest_counter: Any  # Counter
    ingest_latency: Any  # Histogram


def emit_from_ir(handles: EmitHandles, plan: TelemetryPlan) -> dict[str, Any]:
    """Emit traces, logs, and fixed-name metrics for one plan. Caller holds provider lifecycle."""
    tracer = handles.tracer
    otel_logger = get_logger(handles.otel_logger_name)
    trace_id_hex: str | None = None
    span_count = 0

    with tracer.start_as_current_span("ai.ingest.pipeline") as root:
        _apply_resource_to_span(root, plan)
        ctx = get_current()
        tid = root.get_span_context().trace_id
        trace_id_hex = f"{tid:032x}"
        span_count += 1

        sdk_spans: list[Span] = []
        for spec in plan.spans:
            if spec.parent_idx is None:
                parent = root
            else:
                parent = sdk_spans[spec.parent_idx]
            parent_ctx = trace.set_span_in_context(parent)
            sp = tracer.start_span(spec.name, context=parent_ctx)
            for k, v in spec.attributes.items():
                sp.set_attribute(k, v)
            sdk_spans.append(sp)
            span_count += 1

        for log in plan.logs:
            stext, snum = _severity(log.severity_text)
            attrs: dict[str, Any] = dict(log.attributes)
            otel_logger.emit(
                LogRecord(
                    timestamp=time.time_ns(),
                    body=log.body,
                    severity_text=stext,
                    severity_number=snum,
                    context=ctx,
                    attributes=attrs,
                )
            )

        for mp in plan.metrics:
            mattrs = _metric_attr_dict(mp.attributes)
            if mp.kind == "counter":
                handles.ingest_counter.add(int(mp.value), mattrs)
            else:
                handles.ingest_latency.record(float(mp.value), mattrs)

        for sp in reversed(sdk_spans):
            sp.end()

    return {
        "trace_id": trace_id_hex,
        "span_count": span_count,
        "log_count": len(plan.logs),
        "metric_point_count": len(plan.metrics),
    }
