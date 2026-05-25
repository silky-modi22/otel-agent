# otel-agent

Synthetic OpenTelemetry **traces**, **metrics**, and **logs** over **OTLP/HTTP**, plus a **custom OpenTelemetry Collector** built with [ocb](https://github.com/open-telemetry/opentelemetry-collector/blob/main/cmd/builder/README.md).

**New to OpenTelemetry?** Read **[docs/beginner-guide.md](docs/beginner-guide.md)** for a plain-language walkthrough: sample agent → collector → New Relic.

## Prerequisites

- Python 3.11+
- Docker (for `./scripts/build-collector.sh` on any OS, or for Compose)

## Quick start

One-time setup (from your clone of this repo, e.g. `~/extra/otel-agent`):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
./scripts/build-collector.sh
```

### Two terminals (recommended)

Open **two** terminal tabs in the **same directory** (your clone of this repo — **not** the literal path `/path/to/otel-agent`; use something like `~/extra/otel-agent`, or stay put if your prompt already ends with `otel-agent`).

Each helper script prints a **banner** so you can tell which role that window has. _(Reminder text like “wait for Everything is ready” belongs in your head, not pasted into the shell.)_

| Terminal | Command | What you’ll see |
|----------|---------|-----------------|
| **1 — Collector** | `./scripts/run-collector.sh` | Banner, then logs ending with **“Everything is ready”**. When Terminal 2 runs, **large blocks** of `ResourceLog` / `ResourceSpans` / `ResourceMetrics` (the **debug** exporter). |
| **2 — Sample agent** | `./scripts/run-agent.sh` | Banner, then usually **little output** while it sends OTLP to `localhost:4318` (defaults: 20s duration). |

Start **Terminal 1** first and wait for “Everything is ready”, then run **Terminal 2**.

Optional: `./scripts/run-agent.sh --duration 60 --interval 0.4`  

**New Relic:** create `collector/collector-config-nr.yaml` from [`collector/collector-config-nr.yaml.example`](collector/collector-config-nr.yaml.example), set `export NEW_RELIC_LICENSE_KEY="..."`, then Terminal 1: [`./scripts/run-collector-nr.sh`](scripts/run-collector-nr.sh), Terminal 2: `./scripts/run-agent.sh`. (NR config exports **only** to New Relic — no **`debug`** spam in Terminal 1; verify in the NR UI.)

### Same flow without helpers

```bash
./dist/otel-custom/otel-custom --config=collector/collector-config.yaml   # terminal 1
source .venv/bin/activate && python -m agent --duration 10 --interval 0.5   # terminal 2
```

### Send data to New Relic (short version)

1. `cp collector/collector-config-nr.yaml.example collector/collector-config-nr.yaml` and set **`otlphttp/newrelic`** **`endpoint`** if your NR region is not US (see [NR OTLP docs](https://docs.newrelic.com/docs/more-integrations/open-source-telemetry-integrations/opentelemetry/opentelemetry-setup/)).
2. `export NEW_RELIC_LICENSE_KEY="<your-ingest-license-key>"`
3. Terminal 1: `./scripts/run-collector-nr.sh`
4. Terminal 2: `./scripts/run-agent.sh --duration 30`

Details, regional endpoints, and verification: **[docs/beginner-guide.md](docs/beginner-guide.md)** (Phase B).

### Real OpenAI traffic → Collector → New Relic

To observe **real OpenAI Python SDK** calls (not synthetic spans and not the Gemini `/ingest` demo), use OpenTelemetry’s **OpenAI instrumentation** and the same OTLP collector, then forward to New Relic.

1. **NR collector:** follow **[docs/nr-collector-checklist.md](docs/nr-collector-checklist.md)** (copy `collector-config-nr.yaml`, region, `NEW_RELIC_LICENSE_KEY`, `./scripts/run-collector-nr.sh`).
2. **Example app:** follow **[examples/openai_otel/README.md](examples/openai_otel/README.md)** — install `examples/openai_otel/requirements.txt`, set `OPENAI_API_KEY` and `OTEL_SERVICE_NAME`, run `python examples/openai_otel/client.py`.
3. **New Relic UI:** find your service under OpenTelemetry / traces (allow 1–2 minutes).

**Privacy:** avoid enabling Gen AI **message content** capture unless you intend prompts/responses to be stored in NR; see the example README.

### GitHub live events → ingest (demo)

Poll a **public** repo’s activity feed and send each new event to `/ingest` (stdlib poller, no extra deps). Put your token in `export GITHUB_TOKEN=...` or a gitignored **`.github_token`** file in the repo root.

See **[examples/github_ingest/README.md](examples/github_ingest/README.md)**.

### Agent CLI

| Flag | Default | Purpose |
|------|---------|---------|
| `--endpoint` | `http://localhost:4318` | OTLP HTTP base URL |
| `--service-name` | `otel-sample-agent` | `service.name` |
| `--environment` | `dev` | `deployment.environment` |
| `--interval` | `1.0` | Seconds between synthetic requests |
| `--duration` | `0` | Stop after N seconds (`0` = until Ctrl+C) |
| `--error-rate` | `0.05` | Fraction of synthetic 5xx responses |
| `--metric-interval-ms` | `5000` | Metric export period |

Environment variables: `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`, `DEPLOYMENT_ENVIRONMENT`.

### AI-assisted ingest (HTTP + Gemini)

A second mode turns **arbitrary JSON or text** into structured OpenTelemetry (traces, logs, and fixed-name metrics) using the **Gemini API**, then exports **OTLP/HTTP** to the same collector as the synthetic agent.

**Prerequisites:** A Gemini API key available to the server process: `export GEMINI_API_KEY=...`, or a **one-line** gitignored file `.gemini_api_key` in the project root, or `GEMINI_API_KEY_FILE` pointing at a file. Do not send secrets or sensitive personal data to the model.

**Terminal 1** (collector): `./scripts/run-collector.sh`  

**Terminal 2** (HTTP server):

```bash
source .venv/bin/activate
export GEMINI_API_KEY="your-key"
python -m agent serve --http-port 8000 --otel-endpoint http://localhost:4318
```

**Minimal pipeline dashboard:** open `http://127.0.0.1:8000/` after starting `python -m agent serve`.

- Start/stop collector (local debug or New Relic mode)
- Trigger one-shot pipelines: synthetic agent, sample AI ingest, GitHub poll once
- View status checks and recent collector/job output

**Send data** (example):

```bash
curl -sS -X POST http://127.0.0.1:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{"message":"checkout failed","cart_id":"c42","latency_ms":120}' | jq .
```

Optional header: `X-Service-Name: my-service` is passed to the model as a hint for `service.name` metadata on the ingest span.

- `GET /health` — returns `{"status":"ok","gemini_api_key_set":...}` without calling Gemini.
- **Metrics** from the model are limited to counters `ai.ingest.events` and histograms `ai.ingest.latency_ms` (see [agent/telemetry_ir.py](agent/telemetry_ir.py)).

Serve flags: `--otel-endpoint`, `--service-name` (default `otel-ai-ingest`), `--environment`, `--metric-interval-ms`, `--http-host`, `--http-port`, `--gemini-model` (defaults to env `GEMINI_MODEL` or `gemini-2.5-flash` in code).

## Custom collector build

[scripts/build-collector.sh](scripts/build-collector.sh) runs `ocb` inside `otel/opentelemetry-collector-builder:0.129.0`. It sets **GOOS/GOARCH** to match your machine so the binary runs locally (e.g. macOS arm64). Override with `GOOS=linux GOARCH=amd64` for a Linux server artifact.

Manifest: [collector/builder-config.yaml](collector/builder-config.yaml).

Full NR setup, endpoints by region, and troubleshooting: **[docs/beginner-guide.md](docs/beginner-guide.md)** · [New Relic OTLP docs](https://docs.newrelic.com/docs/more-integrations/open-source-telemetry-integrations/opentelemetry/opentelemetry-setup/).

## Docker

```bash
docker compose build collector
docker compose up collector
```

Run the agent on the host against `http://localhost:4318`.
