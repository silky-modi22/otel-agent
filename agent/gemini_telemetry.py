"""Gemini structured JSON → TelemetryPlan."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

_GEMINI_KEY_LINE = re.compile(
    r"^(?:gemini_api_key|google_api_key)\s*=\s*(.+)$",
    re.IGNORECASE,
)

from google import genai
from google.genai import types

from .telemetry_ir import TelemetryPlan

SYSTEM_INSTRUCTION = (
    "You are an OpenTelemetry telemetry planner. The user sends arbitrary "
    "text or JSON describing activity, errors, or domain events.\n\n"
    "Your job is to output a single JSON object matching the TelemetryPlan "
    "schema (no markdown, no prose).\n\n"
    "Rules:\n"
    "- spans: ordered list; parent_idx is null for a direct child of the "
    "pipeline root, or an integer index of a prior span "
    "(0 <= parent_idx < current index).\n"
    "- Use plausible span names (e.g. HTTP semconv: http.method, http.route "
    "as span attributes when relevant).\n"
    "- logs: concise lines; severity_text one of "
    "TRACE|DEBUG|INFO|WARN|ERROR|FATAL.\n"
    "- metrics: only these are allowed:\n"
    '  - kind "counter" with name "ai.ingest.events" — small int increments; '
    "add distinguishing attributes.\n"
    '  - kind "histogram" with name "ai.ingest.latency_ms" — latency in ms '
    "(non-negative float).\n"
    "- resource: optional; service_name and deployment_environment are hints "
    "mapped to ingest metadata on spans (not OTLP Resource).\n"
    "- Keep spans, logs, and metrics small; omit noise.\n\n"
    "Do not invent OTLP endpoints or API keys. Output JSON only."
)


def _read_key_file(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            s = f.read().strip()
    except OSError:
        return None
    return s or None


def _read_gemini_key_from_file(path: str) -> str | None:
    """Load Gemini key from a file: supports KEY=value lines or a single raw key line."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.strip():
        return None
    for line in text.splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        m = _GEMINI_KEY_LINE.match(raw)
        if m:
            return m.group(1).strip().strip("'\"")
    lines = [
        ln.strip()
        for ln in text.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    if not lines:
        return None
    if all("=" not in ln for ln in lines):
        return lines[0]
    return None


def resolve_api_key() -> str | None:
    """Return Gemini API key from env or optional local file (never log this)."""
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if key and key.strip():
        return key.strip()
    path_file = (os.environ.get("GEMINI_API_KEY_FILE") or "").strip()
    if path_file:
        got = _read_gemini_key_from_file(path_file)
        if got:
            return got
    root = Path(__file__).resolve().parents[1]
    got = _read_gemini_key_from_file(str(root / ".gemini_api_key"))
    if got:
        return got
    return None


def _api_key() -> str:
    key = resolve_api_key()
    if not key:
        raise RuntimeError(
            "Set GEMINI_API_KEY or GOOGLE_API_KEY, or create a one-line file "
            "`.gemini_api_key` in the project root, or set GEMINI_API_KEY_FILE "
            "to a file path containing the key."
        )
    return key


def _payload_to_text(raw: Any) -> str:
    if isinstance(raw, str):
        return raw
    try:
        return json.dumps(raw, indent=2, default=str)[:200_000]
    except TypeError:
        return str(raw)[:200_000]


def _extract_json_blob(text: str) -> str:
    """Strip optional markdown fences; return JSON object text."""
    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


def generate_telemetry_plan(
    raw_payload: Any,
    *,
    model: str | None = None,
) -> TelemetryPlan:
    """Call Gemini; parse JSON from text; validate as TelemetryPlan.

    We avoid ``response_mime_type`` / ``response_schema`` because some Gemini
    API versions reject JSON Schema features such as ``additionalProperties``.
    """
    model_id = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    client = genai.Client(api_key=_api_key())
    user_text = (
        "Convert the following input into a TelemetryPlan JSON object.\n"
        "Reply with raw JSON only (no markdown, no code fences, no commentary).\n\n"
        + _payload_to_text(raw_payload)
    )

    response = client.models.generate_content(
        model=model_id,
        contents=user_text,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
        ),
    )

    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, TelemetryPlan):
        return parsed

    text = _extract_json_blob((getattr(response, "text", None) or "").strip())
    if not text:
        raise ValueError("Empty response from Gemini")
    try:
        return TelemetryPlan.model_validate_json(text)
    except Exception as exc:
        raise ValueError(f"Failed to validate Gemini JSON: {exc}") from exc
