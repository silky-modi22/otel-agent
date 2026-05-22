"""Optional localhost TCP check before OTLP export."""

from __future__ import annotations

import os
import socket
import sys
from urllib.parse import urlparse


def ensure_collector_tcp(endpoint: str) -> None:
    """Fail fast if OTLP HTTP collector is not listening (localhost only)."""
    if os.environ.get("SKIP_COLLECTOR_CHECK") == "1":
        return
    raw = endpoint.strip().rstrip("/")
    if not raw.startswith("http"):
        raw = "http://" + raw
    u = urlparse(raw)
    host = (u.hostname or "").lower()
    if host not in ("localhost", "127.0.0.1", "::1"):
        return
    port = u.port or 4318
    try:
        socket.create_connection((u.hostname or "localhost", port), timeout=1.5)
    except OSError as exc:
        print(
            "ERROR: No OpenTelemetry Collector on "
            f"{u.hostname}:{port} ({exc}).\n"
            "Start it in another terminal first:\n"
            "  ./scripts/run-collector.sh\n"
            "or:\n"
            "  export NEW_RELIC_LICENSE_KEY=... && ./scripts/run-collector-nr.sh\n"
            "Skip: SKIP_COLLECTOR_CHECK=1 python -m agent serve ...",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
