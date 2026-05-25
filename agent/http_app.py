"""FastAPI HTTP ingest + minimal local pipeline control UI."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from google.genai.errors import APIError
from opentelemetry import metrics, trace
from pydantic import BaseModel, Field

from .collector_check import ensure_collector_tcp
from .emit_from_ir import EmitHandles, emit_from_ir
from .gemini_telemetry import generate_telemetry_plan, resolve_api_key
from .newrelic_client import fetch_summary as fetch_newrelic_summary
from .newrelic_client import nr_status as newrelic_status
from .otel_bootstrap import setup_otel
from .process_manager import ProcessManager

MAX_BODY_BYTES = 256_000
REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = REPO_ROOT / "agent" / "static"
DEFAULT_SAMPLE_INGEST_PAYLOAD: dict[str, Any] = {
    "source": "ui-sample",
    "message": "Checkout latency spiked in production",
    "service": "checkout-api",
    "environment": "dev",
    "latency_ms": 231,
    "status_code": 503,
    "route": "/checkout",
}


class CollectorStartRequest(BaseModel):
    mode: str = Field(default="local", pattern="^(local|newrelic)$")


class SyntheticJobRequest(BaseModel):
    duration: float = Field(default=20.0, gt=0.0, le=300.0)
    interval: float = Field(default=0.5, gt=0.0, le=30.0)


class GitHubPollRequest(BaseModel):
    once: bool = False
    interval_sec: float = Field(default=30.0, gt=1.0, le=300.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    args = app.state._serve_args
    startup_collector_ready = True
    if os.environ.get("SKIP_COLLECTOR_CHECK") != "1":
        try:
            ensure_collector_tcp(args.otlp_endpoint)
        except SystemExit:
            # Keep UI/API server alive so users can start the collector from
            # the dashboard itself.
            startup_collector_ready = False

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
    app.state.process_manager = ProcessManager(REPO_ROOT)
    app.state.startup_collector_ready = startup_collector_ready
    app.state.next_flush_allowed_at = 0.0
    app.state.flush_retry_cooldown_sec = 8.0
    yield
    manager: ProcessManager = app.state.process_manager
    try:
        await manager.stop_collector()
    except RuntimeError:
        pass
    providers.shutdown()


def _flush_providers(app: FastAPI) -> None:
    now = time.monotonic()
    next_allowed = float(getattr(app.state, "next_flush_allowed_at", 0.0))
    if now < next_allowed:
        return
    manager: ProcessManager = app.state.process_manager
    if not manager.collector_listening():
        app.state.next_flush_allowed_at = now + float(
            getattr(app.state, "flush_retry_cooldown_sec", 8.0)
        )
        return

    prov = app.state.providers
    prov.tracer_provider.force_flush()
    prov.meter_provider.force_flush()
    prov.logger_provider.force_flush()
    app.state.next_flush_allowed_at = 0.0


def _build_payload_with_hints(payload: Any, x_service_name: str | None) -> Any:
    hints: list[str] = []
    if x_service_name:
        hints.append(
            f"Optional service.name hint for this ingest: {x_service_name}"
        )
    if hints:
        if isinstance(payload, str):
            return "\n".join(hints) + "\n\n" + payload
        return {"_ingest_hints": hints, "payload": payload}
    return payload


async def _parse_ingest_payload(
    request: Request,
    x_service_name: str | None,
) -> Any:
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Request body too large")

    ctype = (
        (request.headers.get("content-type") or "")
        .split(";")[0]
        .strip()
        .lower()
    )
    if "application/json" in ctype:
        try:
            payload: Any = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=400, detail=f"Invalid JSON: {exc}"
            ) from exc
    else:
        payload = body.decode("utf-8", errors="replace")
    return _build_payload_with_hints(payload, x_service_name)


def _run_ingest_export(app: FastAPI, payload: Any) -> dict[str, Any]:
    model = app.state.gemini_model
    plan = generate_telemetry_plan(payload, model=model)
    summary = emit_from_ir(app.state.handles, plan)
    _flush_providers(app)
    return summary


def _raise_ingest_http_error(exc: Exception) -> None:
    if isinstance(exc, RuntimeError):
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if isinstance(exc, APIError):
        status = getattr(exc, "code", None) or getattr(exc, "status_code", None) or 502
        if status == 429:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        if status is not None and int(status) >= 500:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise HTTPException(
        status_code=500,
        detail=f"Ingest failed: {type(exc).__name__}: {exc}",
    ) from exc


def create_app() -> FastAPI:
    app = FastAPI(title="OTEL AI ingest", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    async def dashboard() -> FileResponse:
        page = STATIC_DIR / "dashboard.html"
        if not page.is_file():
            raise HTTPException(status_code=404, detail="dashboard.html not found")
        return FileResponse(page)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "gemini_api_key_set": resolve_api_key() is not None,
        }

    @app.get("/api/status")
    async def api_status() -> dict[str, Any]:
        manager: ProcessManager = app.state.process_manager
        return {
            "status": "ok",
            "gemini_api_key_set": resolve_api_key() is not None,
            "new_relic_query": newrelic_status(REPO_ROOT),
            "startup_collector_ready": app.state.startup_collector_ready,
            **manager.status(),
        }

    @app.get("/api/logs")
    async def api_logs() -> dict[str, Any]:
        manager: ProcessManager = app.state.process_manager
        return {"status": "ok", **manager.logs()}

    @app.post("/api/logs/clear")
    async def api_logs_clear() -> dict[str, Any]:
        manager: ProcessManager = app.state.process_manager
        return await manager.clear_logs()

    @app.post("/api/collector/start")
    async def api_collector_start(body: CollectorStartRequest) -> dict[str, Any]:
        manager: ProcessManager = app.state.process_manager
        try:
            result = await manager.start_collector(body.mode)
        except RuntimeError as exc:
            message = str(exc)
            code = 409 if "already running" in message else 503
            raise HTTPException(status_code=code, detail=message) from exc
        return result

    @app.post("/api/collector/stop")
    async def api_collector_stop() -> dict[str, Any]:
        manager: ProcessManager = app.state.process_manager
        try:
            return await manager.stop_collector()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/pipelines/synthetic-agent")
    async def api_run_synthetic_agent(
        body: SyntheticJobRequest,
    ) -> dict[str, Any]:
        manager: ProcessManager = app.state.process_manager
        if not manager.collector_listening():
            raise HTTPException(
                status_code=503,
                detail="Collector is not listening on 127.0.0.1:4318.",
            )
        try:
            return await manager.start_job(
                name="synthetic-agent",
                command=(
                    sys.executable,
                    "-m",
                    "agent",
                    "--duration",
                    str(body.duration),
                    "--interval",
                    str(body.interval),
                ),
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/pipelines/ingest-sample")
    async def api_run_ingest_sample() -> dict[str, Any]:
        manager: ProcessManager = app.state.process_manager
        if not manager.collector_listening():
            raise HTTPException(
                status_code=503,
                detail="Collector is not listening on 127.0.0.1:4318.",
            )
        if resolve_api_key() is None:
            raise HTTPException(
                status_code=503,
                detail="GEMINI_API_KEY is not configured.",
            )

        try:
            await manager.begin_inline_job("ingest-sample")
            summary = await asyncio.to_thread(
                _run_ingest_export,
                app,
                DEFAULT_SAMPLE_INGEST_PAYLOAD,
            )
            manager.append_inline_log(json.dumps(summary, indent=2))
            await manager.end_inline_job(
                exit_code=0, message="Sample ingest exported."
            )
        except Exception as exc:
            await manager.end_inline_job(
                exit_code=1, message=f"Sample ingest failed: {exc}"
            )
            _raise_ingest_http_error(exc)

        summary["status"] = "exported"
        return summary

    @app.post("/api/pipelines/github-poll")
    async def api_run_github_poll(body: GitHubPollRequest) -> dict[str, Any]:
        manager: ProcessManager = app.state.process_manager
        if not manager.collector_listening():
            raise HTTPException(
                status_code=503,
                detail="Collector is not listening on 127.0.0.1:4318.",
            )
        if not manager.github_token_set():
            raise HTTPException(
                status_code=503,
                detail="No GitHub token found. Set GITHUB_TOKEN or create .github_token.",
            )
        try:
            return await manager.start_job(
                name="github-poll-once",
                command=(sys.executable, "examples/github_ingest/poller.py"),
                env={
                    "GITHUB_POLL_ONCE": "1" if body.once else "0",
                    "GITHUB_POLL_INTERVAL_SEC": str(body.interval_sec),
                    "INGEST_URL": "http://127.0.0.1:8000/ingest",
                },
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/pipelines/github-poll/stop")
    async def api_stop_github_poll() -> dict[str, Any]:
        manager: ProcessManager = app.state.process_manager
        try:
            return await manager.stop_job(expected_name="github-poll-once")
        except RuntimeError as exc:
            return {"status": "noop", "job": "github-poll-once", "detail": str(exc)}

    @app.post("/api/pipelines/stop")
    async def api_stop_any_pipeline() -> dict[str, Any]:
        manager: ProcessManager = app.state.process_manager
        try:
            return await manager.stop_job()
        except RuntimeError as exc:
            return {"status": "noop", "detail": str(exc)}

    @app.post("/api/stop-all")
    async def api_stop_all() -> dict[str, Any]:
        manager: ProcessManager = app.state.process_manager
        try:
            pipeline_result = await manager.stop_job()
        except RuntimeError as exc:
            pipeline_result = {"status": "noop", "detail": str(exc)}
        collector_result = await manager.stop_collector()
        logs_result = await manager.clear_logs()
        return {
            "status": "ok",
            "results": {
                "pipeline": pipeline_result,
                "collector": collector_result,
                "logs": logs_result,
            },
        }

    @app.get("/api/newrelic/summary")
    async def api_newrelic_summary() -> dict[str, Any]:
        try:
            summary = await asyncio.to_thread(fetch_newrelic_summary, REPO_ROOT)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"status": "ok", **summary}

    @app.post("/ingest")
    async def ingest(
        request: Request,
        x_service_name: Annotated[
            str | None, Header(alias="X-Service-Name")
        ] = None,
    ) -> JSONResponse:
        payload = await _parse_ingest_payload(request, x_service_name)

        try:
            summary = await asyncio.to_thread(_run_ingest_export, app, payload)
        except Exception as exc:
            _raise_ingest_http_error(exc)

        summary["status"] = "exported"
        return JSONResponse(summary)

    return app
