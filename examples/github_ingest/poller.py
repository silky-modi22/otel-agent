"""Poll public GitHub repo events and POST each new event to OTEL AI ingest (/ingest).

Requires: `python -m agent serve` running (Gemini + collector).

Token (pick one):
  export GITHUB_TOKEN="ghp_..."
  export GH_TOKEN="ghp_..."          # GitHub CLI name also accepted
  one-line file: .github_token in repo root (gitignored)
  export GITHUB_TOKEN_FILE=/path/to/file

Optional env:
  GITHUB_REPO=owner/name             default: open-telemetry/opentelemetry-collector
  INGEST_URL=http://127.0.0.1:8000/ingest
  GITHUB_POLL_INTERVAL_SEC=60
  GITHUB_POLL_ONCE=1                 exit after one poll (good for demo)
  GITHUB_EVENTS_PER_POLL=10          max events to consider per request
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

GITHUB_API = "https://api.github.com"
DEFAULT_REPO = "open-telemetry/opentelemetry-collector"
DEFAULT_INGEST = "http://127.0.0.1:8000/ingest"


def _read_token_file(path: str) -> str | None:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.strip():
        return None
    for line in text.splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        lower = raw.lower()
        if lower.startswith("github_token=") or lower.startswith("gh_token="):
            return raw.split("=", 1)[1].strip().strip("'\"")
    lines = [
        ln.strip()
        for ln in text.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    if lines and all("=" not in ln for ln in lines):
        return lines[0]
    return None


def resolve_github_token() -> str | None:
    for key in ("GITHUB_TOKEN", "GH_TOKEN"):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    path_file = os.environ.get("GITHUB_TOKEN_FILE", "").strip()
    if path_file:
        got = _read_token_file(path_file)
        if got:
            return got
    root = Path(__file__).resolve().parents[2]
    got = _read_token_file(str(root / ".github_token"))
    if got:
        return got
    return None


def _github_request(path: str, token: str | None) -> Any:
    url = f"{GITHUB_API}{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "otel-agent-github-demo",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"GitHub API {exc.code}: {body}") from exc


def _event_summary(ev: dict[str, Any], repo: str) -> dict[str, Any]:
    actor = (ev.get("actor") or {}).get("login")
    payload = ev.get("payload") or {}
    return {
        "source": "github",
        "repo": repo,
        "event_id": ev.get("id"),
        "event_type": ev.get("type"),
        "created_at": ev.get("created_at"),
        "actor": actor,
        "summary": _human_summary(ev.get("type"), payload, actor),
        "payload": _trim_payload(payload),
    }


def _human_summary(event_type: str | None, payload: dict[str, Any], actor: str | None) -> str:
    et = event_type or "UnknownEvent"
    who = actor or "someone"
    if et == "PushEvent":
        ref = payload.get("ref", "")
        n = len(payload.get("commits") or [])
        return f"{who} pushed {n} commit(s) to {ref}"
    if et == "IssuesEvent":
        action = payload.get("action", "")
        issue = payload.get("issue") or {}
        title = (issue.get("title") or "")[:120]
        return f"{who} {action} issue: {title}"
    if et == "PullRequestEvent":
        action = payload.get("action", "")
        pr = payload.get("pull_request") or {}
        title = (pr.get("title") or "")[:120]
        return f"{who} {action} pull request: {title}"
    if et == "WatchEvent":
        return f"{who} starred the repository"
    if et == "ForkEvent":
        return f"{who} forked the repository"
    return f"{who} triggered {et}"


def _trim_payload(payload: dict[str, Any], max_keys: int = 12) -> dict[str, Any]:
    """Keep ingest payload small for Gemini and /ingest body limits."""
    out: dict[str, Any] = {}
    for i, (k, v) in enumerate(payload.items()):
        if i >= max_keys:
            break
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, dict):
            out[k] = {sk: sv for sk, sv in list(v.items())[:8] if isinstance(sv, (str, int, float, bool))}
    return out


def _post_ingest(
    ingest_url: str,
    body: dict[str, Any],
    repo: str,
    *,
    max_retries: int = 4,
) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    owner = repo.split("/", 1)[0] if "/" in repo else repo
    headers = {
        "Content-Type": "application/json",
        "X-Service-Name": f"github-{owner}",
    }
    last_err: RuntimeError | None = None
    for attempt in range(max_retries):
        req = urllib.request.Request(
            ingest_url,
            data=data,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:800]
            last_err = RuntimeError(f"Ingest HTTP {exc.code}: {detail}")
            if exc.code in (429, 503) and attempt + 1 < max_retries:
                time.sleep(min(2**attempt, 8))
                continue
            raise last_err from exc
    if last_err is not None:
        raise last_err
    raise RuntimeError("Ingest failed after retries")


def _event_id_key(raw: Any) -> str | None:
    """GitHub may return event id as string or int depending on API version."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return str(raw)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def run_poll(
    *,
    repo: str,
    token: str | None,
    ingest_url: str,
    interval_sec: float,
    once: bool,
    max_events: int,
    seen: set[str],
) -> int:
    owner, name = repo.split("/", 1)
    path = f"/repos/{owner}/{name}/events?per_page={max_events}"
    events = _github_request(path, token)
    if not isinstance(events, list):
        raise RuntimeError(f"Unexpected GitHub response: {type(events)}")

    # GitHub returns newest first; process oldest-first for stable demo narration
    new_count = 0
    for ev in reversed(events):
        eid_key = _event_id_key(ev.get("id"))
        if eid_key is None or eid_key in seen:
            continue
        seen.add(eid_key)
        body = _event_summary(ev, repo)
        print(
            f"→ ingest: {body['event_type']} id={eid_key} — {body['summary']}",
            flush=True,
        )
        try:
            result = _post_ingest(ingest_url, body, repo)
        except RuntimeError as exc:
            print(f"  WARNING: skipped (ingest failed): {exc}", flush=True)
            continue
        print(
            f"  exported trace_id={result.get('trace_id')} "
            f"spans={result.get('span_count')} logs={result.get('log_count')}",
            flush=True,
        )
        new_count += 1
    if new_count == 0:
        print("(no new events this poll)", flush=True)
    return new_count


def main() -> None:
    token = resolve_github_token()
    if not token:
        print(
            "WARNING: No GITHUB_TOKEN — using unauthenticated API (~60 req/hr).\n"
            "  export GITHUB_TOKEN='ghp_...'\n"
            "  or create a one-line file: .github_token in repo root\n",
            file=sys.stderr,
        )

    repo = os.environ.get("GITHUB_REPO", DEFAULT_REPO).strip()
    if "/" not in repo:
        print("ERROR: GITHUB_REPO must be owner/name", file=sys.stderr)
        raise SystemExit(1)

    ingest_url = os.environ.get("INGEST_URL", DEFAULT_INGEST).strip()
    interval = float(os.environ.get("GITHUB_POLL_INTERVAL_SEC", "60"))
    once = os.environ.get("GITHUB_POLL_ONCE", "").strip() in ("1", "true", "yes")
    max_events = int(os.environ.get("GITHUB_EVENTS_PER_POLL", "10"))

    seen: set[str] = set()
    print(f"GitHub poller: repo={repo} ingest={ingest_url} interval={interval}s", flush=True)

    while True:
        try:
            run_poll(
                repo=repo,
                token=token,
                ingest_url=ingest_url,
                interval_sec=interval,
                once=once,
                max_events=max_events,
                seen=seen,
            )
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        if once:
            break
        time.sleep(interval)


if __name__ == "__main__":
    main()
