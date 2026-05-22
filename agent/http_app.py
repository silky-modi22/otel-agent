"""FastAPI HTTP ingest → Gemini → OTLP export."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from google.genai.errors import APIError
from opentelemetry import metrics, trace

from .collector_check import ensure_collector_tcp
from .emit_from_ir import EmitHandles, emit_from_ir
from .gemini_telemetry import generate_telemetry_plan, resolve_api_key
from .otel_bootstrap import setup_otel

MAX_BODY_BYTES = 256_000


@asynccontextmanager
async def lifespan(app: FastAPI):
    args = app.state._serve_args
    if os.environ.get("SKIP_COLLECTOR_CHECK") != "1":
        ensure_collector_tcp(args.otlp_endpoint)

    providers = setup_otel(
        args.otlp_endpoint,
        service_name=args.service_name,
        environment=args.environment,
        metric_interval_ms=args.metric_interval_ms,
    )
    meter = metrics.get_meter(__name__)
    ingest_counter = meter.create_counter(
        "ai.ingest.events",
        unit="1",
        description="AI ingest-derived notable events",
    )
    ingest_latency = meter.create_histogram(
        "ai.ingest.latency_ms",
        unit="ms",
        description="AI ingest-derived latency samples",
    )
    handles = EmitHandles(
        tracer=trace.get_tracer(__name__),
        otel_logger_name=__name__,
        ingest_counter=ingest_counter,
        ingest_latency=ingest_latency,
    )
    app.state.providers = providers
    app.state.handles = handles
    app.state.gemini_model = args.gemini_model
    yield
    providers.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(title="OTEL AI ingest", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "gemini_api_key_set": resolve_api_key() is not None,
        }

    @app.post("/ingest")
    async def ingest(
        request: Request,
        x_service_name: Annotated[str | None, Header(alias="X-Service-Name")] = None,
    ) -> JSONResponse:
        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Request body too large")

        ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
        if "application/json" in ctype:
            try:
                payload: Any = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc
        else:
            payload = body.decode("utf-8", errors="replace")

        hints: list[str] = []
        if x_service_name:
            hints.append(f"Optional service.name hint for this ingest: {x_service_name}")

        if hints:
            if isinstance(payload, str):
                payload = "\n".join(hints) + "\n\n" + payload
            else:
                payload = {"_ingest_hints": hints, "payload": payload}

        model = app.state.gemini_model

        def _run() -> dict[str, Any]:
            plan = generate_telemetry_plan(payload, model=model)
            summary = emit_from_ir(app.state.handles, plan)
            prov = app.state.providers
            prov.tracer_provider.force_flush()
            prov.meter_provider.force_flush()
            prov.logger_provider.force_flush()
            return summary

        try:
            summary = await asyncio.to_thread(_run)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except APIError as exc:
            status = getattr(exc, "code", None) or getattr(exc, "status_code", None) or 502
            if status == 429:
                raise HTTPException(status_code=429, detail=str(exc)) from exc
            if status is not None and int(status) >= 500:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Ingest failed: {type(exc).__name__}: {exc}"
            ) from exc

        summary["status"] = "exported"
        return JSONResponse(summary)

    return app
