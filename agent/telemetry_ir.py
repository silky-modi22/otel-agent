"""Bounded intermediate representation for AI → OpenTelemetry mapping."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

MAX_SPANS = 48
MAX_LOGS = 64
MAX_METRIC_POINTS = 32
MAX_ATTR_KEYS = 32
MAX_ATTR_STR_LEN = 1024
MAX_LOG_BODY_LEN = 8192
MAX_SPAN_NAME_LEN = 256
MAX_RESOURCE_EXTRA_KEYS = 16

_ATTR_KEY_RE = re.compile(r"^[a-zA-Z0-9_.\-]{1,128}$")

AllowedCounterName = Literal["ai.ingest.events"]
AllowedHistogramName = Literal["ai.ingest.latency_ms"]


def _validate_attr_key(k: str) -> str:
    if not _ATTR_KEY_RE.match(k):
        raise ValueError(f"invalid attribute key: {k!r}")
    return k


def _truncate_str(s: str, max_len: int) -> str:
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


class ResourceOverride(BaseModel):
    """Mapped onto the root ingest span as telemetry.ingest.resource.* (not OTLP Resource)."""

    service_name: str | None = Field(default=None, max_length=256)
    deployment_environment: str | None = Field(default=None, max_length=64)
    extra_attributes: dict[str, str | int | float | bool] = Field(default_factory=dict)

    @field_validator("extra_attributes")
    @classmethod
    def _limit_extra(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(v) > MAX_RESOURCE_EXTRA_KEYS:
            raise ValueError(f"extra_attributes: at most {MAX_RESOURCE_EXTRA_KEYS} keys")
        out: dict[str, str | int | float | bool] = {}
        for key, val in v.items():
            _validate_attr_key(key)
            if isinstance(val, str):
                out[key] = _truncate_str(val, MAX_ATTR_STR_LEN)
            elif isinstance(val, (int, float, bool)):
                out[key] = val
            else:
                raise ValueError(f"extra_attributes[{key!r}]: unsupported type")
        return out


class SpanSpec(BaseModel):
    name: str = Field(max_length=MAX_SPAN_NAME_LEN)
    parent_idx: int | None = None
    attributes: dict[str, str | int | float | bool] = Field(default_factory=dict)

    @field_validator("attributes")
    @classmethod
    def _attrs(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(v) > MAX_ATTR_KEYS:
            raise ValueError(f"attributes: at most {MAX_ATTR_KEYS} keys")
        out: dict[str, str | int | float | bool] = {}
        for key, val in v.items():
            _validate_attr_key(key)
            if isinstance(val, str):
                out[key] = _truncate_str(val, MAX_ATTR_STR_LEN)
            elif isinstance(val, (int, float, bool)):
                out[key] = val
            else:
                raise ValueError(f"attributes[{key!r}]: unsupported type")
        return out


class LogSpec(BaseModel):
    body: str = Field(max_length=MAX_LOG_BODY_LEN)
    severity_text: str = Field(default="INFO", max_length=32)
    attributes: dict[str, str | int | float | bool] = Field(default_factory=dict)

    @field_validator("body")
    @classmethod
    def _body(cls, v: str) -> str:
        return v if len(v) <= MAX_LOG_BODY_LEN else v[: MAX_LOG_BODY_LEN - 1] + "…"

    @field_validator("attributes")
    @classmethod
    def _attrs(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(v) > MAX_ATTR_KEYS:
            raise ValueError(f"attributes: at most {MAX_ATTR_KEYS} keys")
        out: dict[str, str | int | float | bool] = {}
        for key, val in v.items():
            _validate_attr_key(key)
            if isinstance(val, str):
                out[key] = _truncate_str(val, MAX_ATTR_STR_LEN)
            elif isinstance(val, (int, float, bool)):
                out[key] = val
            else:
                raise ValueError(f"attributes[{key!r}]: unsupported type")
        return out


class MetricPointSpec(BaseModel):
    kind: Literal["counter", "histogram"]
    name: AllowedCounterName | AllowedHistogramName
    value: float = Field(ge=0.0, le=1e12)
    attributes: dict[str, str | int | float | bool] = Field(default_factory=dict)

    @field_validator("attributes")
    @classmethod
    def _attrs(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(v) > MAX_ATTR_KEYS:
            raise ValueError(f"attributes: at most {MAX_ATTR_KEYS} keys")
        out: dict[str, str | int | float | bool] = {}
        for key, val in v.items():
            _validate_attr_key(key)
            if isinstance(val, str):
                out[key] = _truncate_str(val, MAX_ATTR_STR_LEN)
            elif isinstance(val, (int, float, bool)):
                out[key] = val
            else:
                raise ValueError(f"attributes[{key!r}]: unsupported type")
        return out

    @model_validator(mode="after")
    def _kind_matches_name(self) -> MetricPointSpec:
        if self.kind == "counter" and self.name != "ai.ingest.events":
            raise ValueError("counter metrics must use name 'ai.ingest.events'")
        if self.kind == "histogram" and self.name != "ai.ingest.latency_ms":
            raise ValueError("histogram metrics must use name 'ai.ingest.latency_ms'")
        return self


class TelemetryPlan(BaseModel):
    """Root document returned by Gemini and validated before export."""

    resource: ResourceOverride | None = None
    spans: list[SpanSpec] = Field(default_factory=list)
    logs: list[LogSpec] = Field(default_factory=list)
    metrics: list[MetricPointSpec] = Field(default_factory=list)

    @field_validator("logs")
    @classmethod
    def _logs_len(cls, v: list[LogSpec]) -> list[LogSpec]:
        if len(v) > MAX_LOGS:
            raise ValueError(f"logs: at most {MAX_LOGS} items")
        return v

    @field_validator("metrics")
    @classmethod
    def _metrics_len(cls, v: list[MetricPointSpec]) -> list[MetricPointSpec]:
        if len(v) > MAX_METRIC_POINTS:
            raise ValueError(f"metrics: at most {MAX_METRIC_POINTS} items")
        return v

    @field_validator("spans")
    @classmethod
    def _spans_len(cls, v: list[SpanSpec]) -> list[SpanSpec]:
        if len(v) > MAX_SPANS:
            raise ValueError(f"spans: at most {MAX_SPANS} items")
        return v

    @model_validator(mode="after")
    def _parent_indices(self) -> TelemetryPlan:
        for i, s in enumerate(self.spans):
            if s.parent_idx is None:
                continue
            if s.parent_idx < 0 or s.parent_idx >= i:
                raise ValueError(
                    f"spans[{i}].parent_idx must refer to a prior span (0..{i - 1})"
                )
        return self
