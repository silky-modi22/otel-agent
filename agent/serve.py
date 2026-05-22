"""CLI: `python -m agent serve` — HTTP ingest + Gemini + OTLP."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass

import uvicorn


@dataclass
class ServeArgs:
    otlp_endpoint: str
    service_name: str
    environment: str
    metric_interval_ms: int
    http_host: str
    http_port: int
    gemini_model: str | None


def parse_serve_args() -> ServeArgs:
    p = argparse.ArgumentParser(
        description="Run HTTP ingest server: POST /ingest → Gemini → OTLP/HTTP."
    )
    p.add_argument(
        "--otel-endpoint",
        default=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318"),
        help="OTLP HTTP base URL for export",
    )
    p.add_argument(
        "--service-name",
        default=os.environ.get("OTEL_SERVICE_NAME", "otel-ai-ingest"),
        help="service.name resource attribute",
    )
    p.add_argument(
        "--environment",
        default=os.environ.get("DEPLOYMENT_ENVIRONMENT", "dev"),
        help="deployment.environment resource attribute",
    )
    p.add_argument(
        "--metric-interval-ms",
        type=int,
        default=5000,
        help="Periodic metric export interval in milliseconds",
    )
    p.add_argument(
        "--http-host",
        default=os.environ.get("OTEL_AI_HTTP_HOST", "127.0.0.1"),
        help="Bind address for FastAPI",
    )
    p.add_argument(
        "--http-port",
        type=int,
        default=int(os.environ.get("OTEL_AI_HTTP_PORT", "8000")),
        help="Port for FastAPI",
    )
    p.add_argument(
        "--gemini-model",
        default=os.environ.get("GEMINI_MODEL"),
        help="Gemini model id (default: env GEMINI_MODEL or gemini-2.5-flash in client)",
    )
    ns = p.parse_args()
    return ServeArgs(
        otlp_endpoint=ns.otel_endpoint,
        service_name=ns.service_name,
        environment=ns.environment,
        metric_interval_ms=ns.metric_interval_ms,
        http_host=ns.http_host,
        http_port=ns.http_port,
        gemini_model=ns.gemini_model,
    )


def run_serve() -> None:
    args = parse_serve_args()
    from .http_app import create_app

    app = create_app()
    app.state._serve_args = args
    uvicorn.run(app, host=args.http_host, port=args.http_port, log_level="info")
