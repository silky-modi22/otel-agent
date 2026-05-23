#!/usr/bin/env bash
# Terminal 1: collector with New Relic OTLP export.
# Requires: NEW_RELIC_LICENSE_KEY and collector/collector-config-nr.yaml (see example).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_REL="collector/collector-config-nr.yaml"
CONFIG_ABS="$ROOT/$CONFIG_REL"

if [[ -z "${NEW_RELIC_LICENSE_KEY:-}" ]]; then
  _key_file="${NEW_RELIC_LICENSE_KEY_FILE:-$ROOT/.new_relic_license_key}"
  if [[ -f "$_key_file" ]]; then
    NEW_RELIC_LICENSE_KEY="$(tr -d '[:space:]' < "$_key_file")"
    export NEW_RELIC_LICENSE_KEY
  fi
fi

if [[ -z "${NEW_RELIC_LICENSE_KEY:-}" ]]; then
  echo "Missing NEW_RELIC_LICENSE_KEY."
  echo "Export your New Relic ingest license key in this shell, or create a one-line file:"
  echo "  export NEW_RELIC_LICENSE_KEY=\"<your-key>\""
  echo "  echo '<your-key>' > .new_relic_license_key"
  exit 1
fi

if [[ "$NEW_RELIC_LICENSE_KEY" == *"your"* && "$NEW_RELIC_LICENSE_KEY" == *"here"* ]]; then
  echo "NEW_RELIC_LICENSE_KEY looks like a placeholder, not a real ingest key."
  echo "Use the Ingest / License key from New Relic (often starts with NRAK-)."
  exit 1
fi

if [[ ! -f "$CONFIG_ABS" ]]; then
  echo "Missing $CONFIG_REL"
  echo "Create it from the template:"
  echo "  cp collector/collector-config-nr.yaml.example collector/collector-config-nr.yaml"
  echo "Edit otlphttp/newrelic endpoint if your NR region is not US."
  exit 1
fi

exec "$ROOT/scripts/run-collector.sh" "$CONFIG_REL"
