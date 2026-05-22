"""Synthetic traces, metrics, and logs exported via OTLP/HTTP."""

from __future__ import annotations

import argparse
import os
import random
import sys
import time
from typing import Sequence

from opentelemetry import metrics, trace
from opentelemetry._logs import LogRecord, get_logger
from opentelemetry._logs.severity import SeverityNumber
from opentelemetry.context import get_current

from .collector_check import ensure_collector_tcp
from .otel_bootstrap import setup_otel

DEFAULT_ROUTES: Sequence[str] = ("/api/users", "/api/orders", "/health")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Emit synthetic OpenTelemetry traces, metrics, and logs (OTLP/HTTP)."
    )
    p.add_argument(
        "--endpoint",
        default=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318"),
        help="OTLP HTTP base URL (trailing path optional). Default: %(default)s",
    )
    p.add_argument(
        "--service-name",
        default=os.environ.get("OTEL_SERVICE_NAME", "otel-sample-agent"),
        help="service.name resource attribute",
    )
    p.add_argument(
        "--environment",
        default=os.environ.get("DEPLOYMENT_ENVIRONMENT", "dev"),
        help="deployment.environment resource attribute",
    )
    p.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Seconds between emission cycles",
    )
    p.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="Stop after this many seconds (0 = run until interrupted)",
    )
    p.add_argument(
        "--error-rate",
        type=float,
        default=0.05,
        help="Probability of a 5xx response (0..1)",
    )
    p.add_argument(
        "--route-prefix",
        default="",
        help="Prefix for synthetic HTTP routes",
    )
    p.add_argument(
        "--metric-interval-ms",
        type=int,
        default=5000,
        help="Periodic metric export interval in milliseconds",
    )
    return p.parse_args()


def _pick_http_status(error_rate: float) -> int:
    if random.random() < error_rate:
        return random.choice((500, 502, 503))
    return random.choice((200, 201, 204))


def run_emit_loop() -> None:
    args = _parse_args()
    ensure_collector_tcp(args.endpoint)
    providers = setup_otel(
        args.endpoint,
        service_name=args.service_name,
        environment=args.environment,
        metric_interval_ms=args.metric_interval_ms,
    )

    otel_logger = get_logger(__name__)
    tracer = trace.get_tracer(__name__)
    meter = metrics.get_meter(__name__)

    request_counter = meter.create_counter(
        "sample.http.server.requests",
        unit="1",
        description="Synthetic HTTP server requests",
    )
    error_counter = meter.create_counter(
        "sample.http.server.errors",
        unit="1",
        description="Synthetic HTTP 5xx responses",
    )
    latency_hist = meter.create_histogram(
        "sample.http.server.duration",
        unit="ms",
        description="Synthetic request duration",
    )

    routes = tuple(f"{args.route_prefix}{r}" for r in DEFAULT_ROUTES)
    deadline = time.monotonic() + args.duration if args.duration > 0 else None

    try:
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                break

            route = random.choice(routes)
            status = _pick_http_status(args.error_rate)

            with tracer.start_as_current_span("HTTP GET") as span:
                span.set_attribute("http.route", route)
                span.set_attribute("http.method", "GET")
                span.set_attribute("http.status_code", status)

                with tracer.start_as_current_span("fetch_dependencies"):
                    time.sleep(random.uniform(0.001, 0.02))

                lat_ms = min(random.expovariate(1 / 25) * 1000, 5000.0)
                attrs = {"http.route": route, "http.status_code": str(status)}
                latency_hist.record(lat_ms, attrs)
                request_counter.add(1, attrs)
                if status >= 500:
                    error_counter.add(1, {"http.route": route})

                msg = f"GET {route} -> {status}"
                otel_logger.emit(
                    LogRecord(
                        timestamp=time.time_ns(),
                        body=msg,
                        severity_text="ERROR" if status >= 500 else "INFO",
                        severity_number=(
                            SeverityNumber.ERROR
                            if status >= 500
                            else SeverityNumber.INFO
                        ),
                        context=get_current(),
                        attributes={
                            "http.route": route,
                            "http.status_code": status,
                        },
                    )
                )

            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        providers.shutdown()


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        from .serve import run_serve

        sys.argv = [sys.argv[0]] + sys.argv[2:]
        run_serve()
        return
    run_emit_loop()


if __name__ == "__main__":
    main()
