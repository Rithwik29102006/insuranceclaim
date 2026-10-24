"""Tavily search client for ClaimCheck 2.0.

Provides external regulatory and statutory query capabilities via the Tavily REST API.
Uses only the Python standard library (urllib) without external dependencies.
Maintains an in-memory audit log for transparency and supports injectable transports for tests.
Never prints, logs, or exposes secret API keys.

Strictly zero emojis and zero decorative Unicode symbols.
"""

from __future__ import annotations

import datetime
import json
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel, Field

from src import settings

TAVILY_API_ENDPOINT = "https://api.tavily.com/search"
DEFAULT_TIMEOUT_SECONDS = 8.0
MAX_RESULTS = 3

# In-memory audit log of all queries made during the session
AUDIT_LOG: List[Dict[str, Any]] = []


class TavilyResultItem(BaseModel):
    """Single search result entry from Tavily."""
    url: str
    title: str
    snippet: str


class TavilySearchResult(BaseModel):
    """Complete structured response from a Tavily search query."""
    query: str
    success: bool
    results: List[TavilyResultItem] = Field(default_factory=list)
    error: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())


def _default_urllib_transport(payload: dict, timeout: float) -> dict:
    """Standard library HTTP transport using urllib.request."""
    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        TAVILY_API_ENDPOINT,
        data=data_bytes,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def search(
    query: str,
    api_key: Optional[str] = None,
    max_results: int = MAX_RESULTS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    transport_fn: Optional[Callable[[dict, float], dict]] = None,
) -> TavilySearchResult:
    """Execute a Tavily search for statutory or regulatory context.

    Args:
        query: Search string derived from an ambiguity or undefined clause.
        api_key: Optional explicit API key; falls back to settings.get_tavily_api_key().
        max_results: Maximum results to retrieve (capped at 3).
        timeout: Request timeout in seconds.
        transport_fn: Optional injectable HTTP transport for offline unit testing.

    Returns:
        TavilySearchResult model containing items, status, and error details.
    """
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    key = api_key or settings.get_tavily_api_key()

    if not key and not transport_fn:
        result = TavilySearchResult(
            query=query,
            success=False,
            error="TAVILY_API_KEY is not set; external guidance unavailable.",
            timestamp=now,
        )
        AUDIT_LOG.append({
            "query": query,
            "urls": [],
            "timestamp": now,
            "success": False,
            "error": "TAVILY_API_KEY not set",
        })
        return result

    effective_key = key or "mock_transport_key"

    payload = {
        "api_key": effective_key,
        "query": query,
        "search_depth": "basic",
        "max_results": min(max_results, MAX_RESULTS),
    }

    transport = transport_fn or _default_urllib_transport

    try:
        raw_resp = transport(payload, timeout)
        items: List[TavilyResultItem] = []
        for r in raw_resp.get("results", []):
            url = str(r.get("url") or "")
            title = str(r.get("title") or "Untitled")
            content = str(r.get("content") or r.get("snippet") or "")
            if url:
                items.append(TavilyResultItem(url=url, title=title, snippet=content))

        result = TavilySearchResult(
            query=query,
            success=True,
            results=items,
            timestamp=now,
        )
        AUDIT_LOG.append({
            "query": query,
            "urls": [item.url for item in items],
            "timestamp": now,
            "success": True,
        })
        return result

    except urllib.error.HTTPError as exc:
        err_msg = f"HTTP error {exc.code} during search"
        AUDIT_LOG.append({"query": query, "urls": [], "timestamp": now, "success": False, "error": err_msg})
        return TavilySearchResult(query=query, success=False, error=err_msg, timestamp=now)
    except urllib.error.URLError as exc:
        err_msg = f"Network connection error: {exc.reason}"
        AUDIT_LOG.append({"query": query, "urls": [], "timestamp": now, "success": False, "error": err_msg})
        return TavilySearchResult(query=query, success=False, error=err_msg, timestamp=now)
    except Exception as exc:
        err_msg = f"Search failed: {type(exc).__name__}: {exc}"
        AUDIT_LOG.append({"query": query, "urls": [], "timestamp": now, "success": False, "error": err_msg})
        return TavilySearchResult(query=query, success=False, error=err_msg, timestamp=now)


def get_audit_log() -> List[Dict[str, Any]]:
    """Return a copy of the in-memory audit log of all Tavily calls."""
    return list(AUDIT_LOG)


def clear_audit_log() -> None:
    """Clear the in-memory audit log (useful between test runs)."""
    AUDIT_LOG.clear()
