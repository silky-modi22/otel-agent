"""Shared OpenTelemetry SDK bootstrap for OTLP/HTTP."""

from __future__ import annotations

import os
from dataclasses import dataclass

from opentelemetry import metrics, trace
from opentelemetry._logs import get_logger, set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def normalize_otlp_endpoint(raw: str) -> str:
    base = raw.strip().rstrip("/")
    return base + "/"


@dataclass
class OtelProviders:
    resource: Resource
    tracer_provider: TracerProvider
    meter_provider: MeterProvider
    logger_provider: LoggerProvider

    def shutdown(self) -> None:
        self.tracer_provider.force_flush()
        self.tracer_provider.shutdown()
        self.meter_provider.force_flush()
        self.meter_provider.shutdown()
        self.logger_provider.force_flush()
        self.logger_provider.shutdown()


def setup_otel(
    endpoint: str,
    *,
    service_name: str,
    environment: str,
    metric_interval_ms: int = 5000,
) -> OtelProviders:
    """Configure OTLP HTTP env, global providers, and return handles for shutdown."""
    normalized = normalize_otlp_endpoint(endpoint)
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = normalized

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
        export_interval_millis=metric_interval_ms,
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    set_logger_provider(logger_provider)

    return OtelProviders(
        resource=resource,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        logger_provider=logger_provider,
    )
