# GitHub events → AI ingest → OpenTelemetry → Collector

Polls **public** repository activity from the [GitHub REST API](https://docs.github.com/en/rest/activity/events#list-repository-events) and sends each new event to `POST /ingest` (Gemini shapes telemetry; same collector path as the rest of this repo).

## Where to put your GitHub token

Use **one** of these (never commit the token to git):

| Method | Example |
|--------|---------|
| **Environment variable (recommended)** | `export GITHUB_TOKEN="ghp_..."` |
| **GitHub CLI name** | `export GH_TOKEN="ghp_..."` |
| **Gitignored file in repo root** | Create `.github_token` with a single line: your token |
| **Custom file path** | `export GITHUB_TOKEN_FILE="$HOME/.secrets/github"` |

The poller also works **without** a token for public repos, but you only get ~**60 requests/hour** — use a token for demos.

`.github_token` is listed in `.gitignore` (same idea as `.gemini_api_key`).

## Prerequisites

1. **Collector** running: `./scripts/run-collector.sh` (or NR variant).
2. **Ingest server** running with Gemini configured:

   ```bash
   ./scripts/run-serve.sh
   ```

   If port 8000 is busy: `KILL_EXISTING=1 ./scripts/run-serve.sh`  
   Or use `.gemini_api_key` in repo root (no `export` needed).

3. **GitHub token** (optional but recommended): [fine-grained](https://github.com/settings/personal-access-tokens/new) or [classic](https://github.com/settings/tokens/new) with **`public_repo`** if you poll repos you do not own.

## Run (Terminal 3)

From repo root:

```bash
export GITHUB_TOKEN="ghp_your_token_here"
export GITHUB_REPO="open-telemetry/opentelemetry-collector"   # any public owner/repo
export INGEST_URL="http://127.0.0.1:8000/ingest"

# One poll then exit (good for first test):
export GITHUB_POLL_ONCE=1
python examples/github_ingest/poller.py
```

Continuous demo (poll every 60s):

```bash
export GITHUB_POLL_INTERVAL_SEC=60
python examples/github_ingest/poller.py
```

Watch **Terminal 1** (collector) for `ResourceSpans` / logs after each successful ingest.

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `GITHUB_TOKEN` / `GH_TOKEN` | — | API auth (higher rate limits) |
| `GITHUB_TOKEN_FILE` | — | Path to file containing token |
| `.github_token` | — | One-line token in repo root |
| `GITHUB_REPO` | `open-telemetry/opentelemetry-collector` | `owner/name` to watch |
| `INGEST_URL` | `http://127.0.0.1:8000/ingest` | AI ingest endpoint |
| `GITHUB_POLL_INTERVAL_SEC` | `60` | Seconds between polls |
| `GITHUB_POLL_ONCE` | — | Set to `1` to run one poll and exit |
| `GITHUB_EVENTS_PER_POLL` | `10` | Max events returned per GitHub request |

## Flow

```text
GitHub API (repo events)
    → poller.py (dedupe by event id)
    → POST /ingest (Gemini → TelemetryPlan)
    → OTLP → collector :4318
```

No extra pip packages — uses Python stdlib only.
