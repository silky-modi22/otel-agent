# New Relic collector checklist

Use this when running the **custom collector** with OTLP forwarded to **New Relic** (not the local `debug` exporter).

## 1. Config file (local only; gitignored)

```bash
cp collector/collector-config-nr.yaml.example collector/collector-config-nr.yaml
```

Edit `collector/collector-config-nr.yaml`:

- **`exporters.otlphttp/newrelic.endpoint`** — must match your New Relic **data region** (wrong region often yields **403**). Examples:
  - US: `https://otlp.nr-data.net`
  - EU: `https://otlp.eu01.nr-data.net`
- **`headers.api-key`** — keep `${env:NEW_RELIC_LICENSE_KEY}` so the key is not stored in the file.

See [New Relic OTLP setup](https://docs.newrelic.com/docs/more-integrations/open-source-telemetry-integrations/opentelemetry/opentelemetry-setup/) for your account’s endpoint.

## 2. Ingest license key in the shell

Use the **Ingest / License** API key from New Relic (not unrelated “user” keys unless NR docs say otherwise):

```bash
export NEW_RELIC_LICENSE_KEY="<your-ingest-license-key>"
```

No spaces after `=`. Export in the **same** terminal where you start the collector (or use your process manager’s env).

## 3. Build the collector binary (once)

```bash
./scripts/build-collector.sh
```

Produces `dist/otel-custom/otel-custom`.

## 4. Start the collector with NR config

```bash
./scripts/run-collector-nr.sh
```

This invokes [`scripts/run-collector.sh`](../scripts/run-collector.sh) with `collector/collector-config-nr.yaml`. Wait for **Everything is ready**. OTLP HTTP listens on **4318**.

## 5. Verify

- Collector logs: no repeating **401 / 403** toward NR’s OTLP host.
- New Relic UI: **APM / OpenTelemetry** (or distributed tracing) for your `service.name` — allow **1–2 minutes** after first spans.

## Troubleshooting

| Symptom | Likely cause |
|--------|----------------|
| **403** on `otlp.nr-data.net` | Wrong **region** endpoint or wrong **key type** |
| Collector exits: missing config | Create `collector/collector-config-nr.yaml` from the example |
| Collector exits: missing key | `NEW_RELIC_LICENSE_KEY` not set in the shell running the script |

Longer walkthrough: **[beginner-guide.md](beginner-guide.md)** (Phase B).
