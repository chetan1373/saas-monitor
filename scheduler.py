"""APScheduler background jobs:
  - smart_poll(): every 1 minute — fetches only due services + triggers per-incident AI
  - global_ai_report(): every N minutes (env configurable) — global health narrative
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import analyzer
import db as database
import fetcher
import normalizer
from config import AI_GLOBAL_REPORT_INTERVAL_MINUTES

logger = logging.getLogger(__name__)


# ── Routing helper ─────────────────────────────────────────────────────────────

async def _normalize_result(
    raw: dict,
    service_cfg: dict,
) -> tuple:
    """Route to the correct normalizer based on page_type."""
    page_type = service_cfg.get("page_type", "statuspage_v2")
    if page_type == "slack":
        return normalizer.normalize_slack_response(raw, service_cfg)
    if page_type == "html":
        extracted = await analyzer.extract_html_status(
            service_name=service_cfg["name"],
            raw_text=raw.get("_raw_text", ""),
        )
        return normalizer.normalize_html_response(extracted, service_cfg)
    return normalizer.normalize_response(raw, service_cfg)


def create_scheduler(pool, default_poll_interval: int = 5) -> AsyncIOScheduler:
    """Build and return a configured (not yet started) AsyncIOScheduler."""
    sched = AsyncIOScheduler(timezone="UTC")

    # Runs every minute; internally decides which services are due
    sched.add_job(
        _smart_poll,
        "interval",
        minutes=1,
        args=[pool],
        id="smart_poll",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Global AI health report
    sched.add_job(
        _global_ai_report,
        "interval",
        minutes=AI_GLOBAL_REPORT_INTERVAL_MINUTES,
        args=[pool],
        id="global_ai_report",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    return sched


# ── Jobs ──────────────────────────────────────────────────────────────────────

async def _smart_poll(pool) -> None:
    """Fetch all services whose poll interval has elapsed, normalize, persist, and analyze."""
    try:
        raw_results = await fetcher.fetch_due_services(pool)
        if not raw_results:
            return

        new_active_ids: list[dict[str, Any]] = []

        for raw in raw_results:
            service_cfg = raw.pop("_service_cfg", {})
            if not service_cfg:
                continue

            try:
                norm_svc, norm_incidents = await _normalize_result(raw, service_cfg)
            except Exception as exc:
                logger.warning("Normalization failed for %s: %s", service_cfg.get("name"), exc)
                continue

            # Update service status in DB
            await database.update_service_status(
                pool,
                norm_svc.slug,
                norm_svc.current_status,
                norm_svc.health_score,
                norm_svc.active_incident_count,
            )

            # Upsert each incident
            for ni in norm_incidents:
                inc_dict = normalizer.incident_to_dict(ni)
                await database.upsert_incident(pool, inc_dict)

                # Queue for AI analysis if active and not yet analyzed
                if ni.is_active and await database.needs_ai_analysis(pool, ni.id):
                    new_active_ids.append(inc_dict)

        if new_active_ids:
            logger.info("Analyzing %d new active incident(s) with AI", len(new_active_ids))
            await _analyze_incidents_batch(pool, new_active_ids)

    except Exception as exc:
        logger.error("smart_poll error: %s", exc, exc_info=True)


async def _analyze_incidents_batch(pool, incidents: list[dict]) -> None:
    """Run AI analysis sequentially to avoid flooding the API."""
    for inc in incidents:
        try:
            summary, impact = await analyzer.analyze_incident(inc)
            if summary:
                await database.update_incident_ai(pool, inc["id"], summary, impact)
        except Exception as exc:
            logger.warning("AI analysis failed for %s: %s", inc.get("id"), exc)


async def _global_ai_report(pool) -> None:
    """Generate and persist a global health narrative."""
    try:
        active = await database.get_active_incidents(pool)
        all_svcs = await database.get_all_services(pool)

        narrative = await analyzer.analyze_global_health(active, all_svcs)

        await database.save_ai_analysis(
            pool,
            "global_health",
            narrative,
            {
                "incident_count": len(active),
                "services_affected": len({i["service_slug"] for i in active}),
                "total_services": len(all_svcs),
            },
        )
        logger.info("Global AI health report saved (%d active incidents)", len(active))
    except Exception as exc:
        logger.error("global_ai_report error: %s", exc, exc_info=True)


# ── Convenience: run both jobs immediately (used by /api/refresh) ─────────────

async def run_full_refresh(pool) -> int:
    """Force-fetch ALL enabled services now, normalize, persist, analyze.
    Returns count of services fetched.
    """
    try:
        raw_results = await fetcher.fetch_all_services_now(pool)
        count = len(raw_results)

        new_active: list[dict] = []

        for raw in raw_results:
            service_cfg = raw.pop("_service_cfg", {})
            if not service_cfg:
                continue
            try:
                norm_svc, norm_incidents = await _normalize_result(raw, service_cfg)
            except Exception as exc:
                logger.warning("Normalization failed for %s: %s", service_cfg.get("name"), exc)
                continue

            await database.update_service_status(
                pool,
                norm_svc.slug,
                norm_svc.current_status,
                norm_svc.health_score,
                norm_svc.active_incident_count,
            )
            for ni in norm_incidents:
                inc_dict = normalizer.incident_to_dict(ni)
                await database.upsert_incident(pool, inc_dict)
                if ni.is_active and await database.needs_ai_analysis(pool, ni.id):
                    new_active.append(inc_dict)

        if new_active:
            await _analyze_incidents_batch(pool, new_active)

        # Also refresh the global AI report
        await _global_ai_report(pool)

        return count
    except Exception as exc:
        logger.error("run_full_refresh error: %s", exc, exc_info=True)
        return 0
