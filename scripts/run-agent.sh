#!/usr/bin/env bash
# Run in **Terminal 2** after Terminal 1 shows "Everything is ready".
# Usage: ./scripts/run-agent.sh [args...]
#   Default (no args):  --duration 20 --interval 0.5
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ ! -d .venv ]]; then
  echo "No .venv in $ROOT"
  echo "Run:  python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate

cat << 'EOF'

================================================================
  TERMINAL 2 — Sample OTLP agent (this window)
================================================================
  Role: Generates fake traces, metrics, logs and POSTs them to
        http://localhost:4318

  What you should see:
  - This script prints the command, then often little or no output
    while the agent runs (that is normal).
  - If Terminal 1 uses collector-config-nr.yaml, it stays quiet on success.
    Check New Relic UI for service.name otel-sample-agent (wait 1–2 min).
  - If Terminal 1 uses collector-config.yaml (debug), watch for ResourceSpans dumps.

  If you see "Connection refused" to port 4318, start Terminal 1 first.
================================================================

EOF

if [[ $# -eq 0 ]]; then
  set -- --duration 20 --interval 0.5
fi

# Fail fast if no collector is listening (avoids noisy Python retry spam).
# Uses Python (always available after venv activate); does not rely on nc(1).
if [[ "${SKIP_COLLECTOR_CHECK:-}" != "1" ]]; then
  _check_port="${OTEL_COLLECTOR_PORT:-4318}"
  _skip_check="${OTEL_EXPORTER_OTLP_ENDPOINT:-}"
  if [[ -n "$_skip_check" ]] && [[ "$_skip_check" != *"localhost"* ]] && [[ "$_skip_check" != *"127.0.0.1"* ]]; then
    :
  elif ! python -c "import socket;s=socket.socket();s.settimeout(1.5);s.connect(('127.0.0.1',${_check_port}));s.close()" 2>/dev/null; then
    echo "ERROR: Nothing is listening on 127.0.0.1:${_check_port} — the OpenTelemetry Collector is not running."
    echo ""
    echo "In another terminal (same repo directory), start it first:"
    echo "  ./scripts/run-collector.sh"
    echo "or with New Relic:"
    echo "  export NEW_RELIC_LICENSE_KEY=\"...\" && ./scripts/run-collector-nr.sh"
    echo ""
    echo "Then run this script again. To skip this check: SKIP_COLLECTOR_CHECK=1 $0 $*"
    exit 1
  fi
fi

echo "Running: python -m agent $*"
echo ""
python -m agent "$@"
echo ""
echo "Agent finished. Telemetry was sent to localhost:4318."
echo "If Terminal 1 uses run-collector-nr.sh, silence there usually means success."
echo "Check New Relic → APM / OpenTelemetry / Traces for service: otel-sample-agent"
echo "(allow 1–2 minutes for data to appear)."
