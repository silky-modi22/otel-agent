"""Minimal real OpenAI call with OpenTelemetry GenAI instrumentation.

Exports OTLP over HTTP. Requires: OPENAI_API_KEY.
Optional: OTEL_EXPORTER_OTLP_ENDPOINT (default http://localhost:4318),
          OTEL_SERVICE_NAME, DEPLOYMENT_ENVIRONMENT
"""

from __future__ import annotations

import os
import sys

from openai import OpenAI
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
    OTLPMetricExporter,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.instrumentation.openai_v2 import OpenAIInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def _normalize_endpoint(raw: str) -> str:
    return raw.strip().rstrip("/") + "/"


def main() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: Set OPENAI_API_KEY.", file=sys.stderr)
        raise SystemExit(1)

    raw_ep = os.environ.get(
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "http://localhost:4318",
    )
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = _normalize_endpoint(raw_ep)

    service_name = os.environ.get("OTEL_SERVICE_NAME", "openai-otel-example")
    environment = os.environ.get("DEPLOYMENT_ENVIRONMENT", "dev")
    resource = Resource.create(
        {
            "service.name": service_name,
            "deployment.environment": environment,
        }
    )

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(),
        export_interval_millis=5000,
    )
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[metric_reader],
    )
    metrics.set_meter_provider(meter_provider)

    OpenAIInstrumentor().instrument()

    client = OpenAI()
    model = os.environ.get("OPENAI_EXAMPLE_MODEL", "gpt-4o-mini")
    prompt = os.environ.get(
        "OPENAI_EXAMPLE_PROMPT",
        "Reply in one short sentence: what is OpenTelemetry used for?",
    )

    print(f"Calling OpenAI model={model!r} …", flush=True)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=80,
    )
    text = (resp.choices[0].message.content or "").strip()
    print("Assistant:", text[:500], flush=True)

    tracer_provider.force_flush()
    meter_provider.force_flush()
    tracer_provider.shutdown()
    meter_provider.shutdown()
    print(
        "OTLP export flushed. Check collector / New Relic for traces and metrics.",
        flush=True,
    )


if __name__ == "__main__":
    main()
