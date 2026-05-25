"""Minimal New Relic NerdGraph client for UI summaries."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

NERDGRAPH_URL = "https://api.newrelic.com/graphql"


def _read_secret_file(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    value = text.strip()
    return value or None


def resolve_user_api_key(repo_root: Path) -> str | None:
    for key in ("NEW_RELIC_USER_API_KEY", "NEW_RELIC_API_KEY"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return _read_secret_file(repo_root / ".new_relic_user_api_key")


def resolve_account_id(repo_root: Path) -> int | None:
    raw = os.environ.get("NEW_RELIC_ACCOUNT_ID", "").strip()
    if not raw:
        raw = (
            _read_secret_file(repo_root / ".new_relic_account_id") or ""
        ).strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def nr_status(repo_root: Path) -> dict[str, Any]:
    api_key = resolve_user_api_key(repo_root)
    account_id = resolve_account_id(repo_root)
    return {
        "configured": bool(api_key and account_id),
        "has_api_key": api_key is not None,
        "has_account_id": account_id is not None,
    }


def _nerdgraph(
    account_id: int, api_key: str, query: str
) -> list[dict[str, Any]]:
    graph_query = (
        "query($accountId:Int!, $nrql:String!) {"
        " actor { account(id: $accountId) {"
        " nrql(query: $nrql) { results } } } }"
    )
    body = {
        "query": graph_query,
        "variables": {"accountId": account_id, "nrql": query},
    }
    req = urllib.request.Request(
        NERDGRAPH_URL,
        method="POST",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "API-Key": api_key},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"NerdGraph HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"NerdGraph network error: {exc}") from exc

    if payload.get("errors"):
        raise RuntimeError(f"NerdGraph errors: {payload['errors']}")
    account = (payload.get("data") or {}).get("actor", {}).get("account", {})
    results = account.get("nrql", {}).get("results", [])
    if isinstance(results, list):
        return results
    return []


def fetch_summary(repo_root: Path) -> dict[str, Any]:
    api_key = resolve_user_api_key(repo_root)
    account_id = resolve_account_id(repo_root)
    if not api_key or not account_id:
        raise RuntimeError(
            "New Relic query not configured. Set NEW_RELIC_USER_API_KEY and "
            "NEW_RELIC_ACCOUNT_ID (or .new_relic_user_api_key and "
            ".new_relic_account_id)."
        )

    queries: dict[str, str] = {
        "spans_15m": (
            "SELECT count(*) AS value FROM Span "
            "WHERE service.name IN ('otel-sample-agent','otel-ai-ingest') "
            "SINCE 15 minutes ago"
        ),
        "logs_15m": (
            "SELECT count(*) AS value FROM Log "
            "WHERE service.name IN ('otel-sample-agent','otel-ai-ingest') "
            "SINCE 15 minutes ago"
        ),
        "errors_15m": (
            "SELECT count(*) AS value FROM Span "
            "WHERE service.name IN ('otel-sample-agent','otel-ai-ingest') "
            "AND error IS true SINCE 15 minutes ago"
        ),
    }
    out: dict[str, Any] = {"queries": {}, "window": "15 minutes"}
    for name, q in queries.items():
        out["queries"][name] = _nerdgraph(account_id, api_key, q)
    return out
