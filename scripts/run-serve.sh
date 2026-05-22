#!/usr/bin/env bash
# Run AI ingest server (Gemini + POST /ingest). Use after collector is on :4318.
# Usage:
#   ./scripts/run-serve.sh
#   KILL_EXISTING=1 ./scripts/run-serve.sh    # stop old process on port 8000 first
#   ./scripts/run-serve.sh --http-port 8001
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PORT="${OTEL_AI_HTTP_PORT:-8000}"

if [[ ! -d .venv ]]; then
  echo "No .venv in $ROOT"
  echo "Run:  python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

if lsof -ti ":${PORT}" >/dev/null 2>&1; then
  if [[ "${KILL_EXISTING:-}" == "1" ]]; then
    echo "Stopping process on port ${PORT}..."
    lsof -ti ":${PORT}" | xargs kill -9 2>/dev/null || true
    sleep 1
  else
    cat <<EOF

ERROR: Port ${PORT} is already in use (another ingest server may be running).

  Option A — use the server that is already running:
    curl -s http://127.0.0.1:${PORT}/health

  Option B — stop it and start fresh:
    kill \$(lsof -ti :${PORT})
    ./scripts/run-serve.sh

  Option C — auto-kill and restart:
    KILL_EXISTING=1 ./scripts/run-serve.sh

  Option D — different port:
    python -m agent serve --http-port 8001
    export INGEST_URL=http://127.0.0.1:8001/ingest

EOF
    exit 1
  fi
fi

# shellcheck disable=SC1091
source .venv/bin/activate

cat <<EOF

================================================================
  TERMINAL 2 — AI ingest server (Gemini + /ingest)
================================================================
  URL: http://127.0.0.1:${PORT}
  Keys: .gemini_api_key or GEMINI_API_KEY in repo root

  GitHub poller (Terminal 3):
    export GITHUB_POLL_ONCE=1
    python examples/github_ingest/poller.py

================================================================

EOF

exec python -m agent serve --http-port "${PORT}" --otel-endpoint "${OTEL_EXPORTER_OTLP_ENDPOINT:-http://localhost:4318}" "$@"
