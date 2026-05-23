#!/usr/bin/env bash
# Run in **Terminal 1** and leave it open. Shows OTLP receive + debug output.
# Usage: ./scripts/run-collector.sh [path/to/config.yaml]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
BIN="$ROOT/dist/otel-custom/otel-custom"
CONFIG="${1:-collector/collector-config.yaml}"
if [[ ! -x "$BIN" ]]; then
  echo "Missing executable: $BIN"
  echo "Build it first:  ./scripts/build-collector.sh"
  exit 1
fi
if [[ ! -f "$CONFIG" ]]; then
  echo "Config not found: $CONFIG"
  exit 1
fi

IS_NR_CONFIG=0
case "$CONFIG" in
  *collector-config-nr.yaml*) IS_NR_CONFIG=1 ;;
esac

if [[ "$IS_NR_CONFIG" -eq 1 ]]; then
  cat << EOF

================================================================
  TERMINAL 1 — OpenTelemetry Collector → New Relic (this window)
================================================================
  Role: Receives OTLP on localhost:4318 and forwards to New Relic.

  What you should see:
  - "Everything is ready. Begin running and processing data."
  - Then mostly silence (NR config has no debug dump).
  - Export problems show as error lines (403, no such host, Dropping data).

  Verify in New Relic UI (1–2 min after Terminal 2 runs):
  service.name = otel-sample-agent

  Config: $CONFIG
  Press Ctrl+C here to stop the collector.
================================================================

EOF
else
  cat << EOF

================================================================
  TERMINAL 1 — OpenTelemetry Collector (this window)
================================================================
  Role: Receives OTLP on your machine
  - HTTP  : http://0.0.0.0:4318  (default config: HTTP only; same as the sample agent)
  - gRPC  is off in the default yaml so another app can use :4317 without conflict.

  What you should see after start:
  - A line containing: "Everything is ready. Begin running and processing data."
  - After you start the sample agent in Terminal 2, large blocks of text
    (ResourceLog, ResourceSpans, ResourceMetrics) = data is flowing.

  Config: $CONFIG
  Press Ctrl+C here to stop the collector.
================================================================

EOF
fi

exec "$BIN" --config="$CONFIG"
