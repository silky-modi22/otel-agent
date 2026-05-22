# Real OpenAI traffic → OpenTelemetry → Collector → New Relic

This example runs **one real** OpenAI `chat.completions` call with the official **`opentelemetry-instrumentation-openai-v2`** package so spans and metrics follow **Gen AI** semantic conventions, then exports **OTLP/HTTP** to the same collector the rest of this repo uses (default `http://localhost:4318`).

It replaces **synthetic** (`python -m agent`) or **Gemini-shaped** (`python -m agent serve`) demo data when you want **production-like LLM observability** in New Relic.

## Prerequisites

- Python 3.11+
- **OpenAI API key**: `OPENAI_API_KEY`
- **Collector** built and running (see repo root `README.md`). For **New Relic**, use the NR config path below.

## Step 1 — New Relic collector (Terminal 1)

Follow **[docs/nr-collector-checklist.md](../../docs/nr-collector-checklist.md)** in short:

1. `cp collector/collector-config-nr.yaml.example collector/collector-config-nr.yaml`
2. Set `otlphttp/newrelic` **endpoint** for your NR **region**
3. `export NEW_RELIC_LICENSE_KEY="..."`  
4. From repo root: `./scripts/run-collector-nr.sh`  
5. Wait for **Everything is ready** (OTLP on **4318**)

For **local debug only** (no NR), use `./scripts/run-collector.sh` instead.

## Step 2 — Install example dependencies (Terminal 2)

From repo root:

```bash
python3 -m venv examples/openai_otel/.venv
source examples/openai_otel/.venv/bin/activate
pip install -r examples/openai_otel/requirements.txt
```

## Step 3 — Run the client

Still in the example venv (or with deps on `PYTHONPATH`):

```bash
cd /path/to/OTEL_Agent   # repo root
export OPENAI_API_KEY="sk-..."   # required
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318"
export OTEL_SERVICE_NAME="openai-otel-example"
# optional: model and prompt
# export OPENAI_EXAMPLE_MODEL="gpt-4o-mini"
# export OPENAI_EXAMPLE_PROMPT="Say hello in 5 words."

python examples/openai_otel/client.py
```

You should see a short assistant reply and a message that OTLP was flushed.

## Step 4 — New Relic UI

Open **Distributed tracing** / **OpenTelemetry** entity for **`OTEL_SERVICE_NAME`**. Look for Gen AI–related span attributes (model, operation, token usage, etc.). Allow **1–2 minutes** for data to appear.

## Privacy and message content

By default, instrumentation does **not** need to record full prompts/responses to be useful (latency, tokens, errors, model id).

If you enable **message content** capture via OpenTelemetry Gen AI env vars (e.g. `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`), prompts and completions may contain **PII** and will flow to the collector and **New Relic** under your retention policy — use only when compliant and necessary.

See the [OpenTelemetry Python OpenAI instrumentation](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation-genai/openai.html) docs for current environment variables.

## Azure OpenAI and other hosts

The `openai_v2` instrumentation supports several OpenAI-compatible systems; set base URL / keys per OpenAI SDK and package docs.
