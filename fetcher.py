"""Async HTTP fetcher — Statuspage v2 JSON and HTML status pages."""

from __future__ import annotations

import asyncio
import logging
from html.parser import HTMLParser
from typing import Any

import httpx

import db as database

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(10.0, connect=5.0)
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "SaaSIncidentMonitor/1.0",
}


# ── HTML tag stripper (stdlib only, no new dependencies) ──────────────────────

class _TextExtractor(HTMLParser):
    """Strip HTML tags and return visible text, skipping script/style blocks."""

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip: set[str] = {"script", "style", "noscript", "head"}
        self._depth: int = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._skip:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._skip and self._depth:
            self._depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._depth:
            t = data.strip()
            if t:
                self._chunks.append(t)

    def get_text(self) -> str:
        return "\n".join(self._chunks)[:8000]  # cap to ~2 k tokens


def _strip_html(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return parser.get_text()


async def fetch_html_service(
    service: dict,
    client: httpx.AsyncClient,
) -> dict[str, Any] | None:
    """Fetch a raw HTML status page and return stripped visible text in a sentinel dict."""
    url = service["api_url"]
    html_headers = {**HEADERS, "Accept": "text/html,application/xhtml+xml"}
    try:
        resp = await client.get(url, timeout=TIMEOUT, headers=html_headers)
        resp.raise_for_status()
        return {
            "_page_type": "html",
            "_service_cfg": service,
            "_raw_text": _strip_html(resp.text),
        }
    except httpx.TimeoutException:
        logger.warning("Timeout fetching HTML %s (%s)", service["name"], url)
    except httpx.HTTPStatusError as exc:
        logger.warning("HTTP %s fetching HTML %s (%s)", exc.response.status_code, service["name"], url)
    except Exception as exc:
        logger.warning("Error fetching HTML %s (%s): %s", service["name"], url, exc)
    return None


async def fetch_service(
    service: dict,
    client: httpx.AsyncClient,
) -> dict[str, Any] | None:
    """Fetch status for one service, routing by page_type.

    Returns the raw data dict (augmented with `_service_cfg`), or None on error.
    """
    if service.get("page_type") == "html":
        return await fetch_html_service(service, client)

    # ── Statuspage v2 JSON (default) ──────────────────────────────────────────
    url = service["api_url"]
    try:
        resp = await client.get(url, timeout=TIMEOUT, headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()
        data["_service_cfg"] = service
        return data
    except httpx.TimeoutException:
        logger.warning("Timeout fetching %s (%s)", service["name"], url)
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "HTTP %s fetching %s (%s)",
            exc.response.status_code,
            service["name"],
            url,
        )
    except Exception as exc:
        logger.warning("Error fetching %s (%s): %s", service["name"], url, exc)
    return None


async def fetch_services_batch(
    services: list[dict],
    client: httpx.AsyncClient,
) -> list[dict[str, Any]]:
    """Fetch a list of services concurrently. Returns only successful results."""
    tasks = [fetch_service(svc, client) for svc in services]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    return [r for r in results if r is not None]


async def fetch_due_services(pool) -> list[dict[str, Any]]:
    """Fetch only services whose poll interval has elapsed since last_checked."""
    due = await database.get_due_services(pool)
    if not due:
        return []
    logger.info("Polling %d due service(s)", len(due))
    async with httpx.AsyncClient() as client:
        return await fetch_services_batch(due, client)


async def fetch_all_services_now(pool) -> list[dict[str, Any]]:
    """Force-fetch ALL enabled services (used by /api/refresh endpoint)."""
    services = await database.get_enabled_services(pool)
    if not services:
        return []
    logger.info("Force-fetching all %d enabled service(s)", len(services))
    async with httpx.AsyncClient() as client:
        return await fetch_services_batch(services, client)
