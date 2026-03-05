"""FastAPI application — lifespan, routes, and static file serving."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

import db as database
import normalizer
import scheduler as sched_module
from config import (
    APP_HOST,
    APP_PORT,
    CATEGORIES,
    DATABASE_URL,
    DEFAULT_POLL_INTERVAL_MINUTES,
    DEFAULT_SERVICES,
)

PAGE_TYPES = ["statuspage_v2", "html", "slack"]

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class ServiceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    api_url: str = Field(..., min_length=10)
    category: str = "Other"
    website: str = ""
    logo_url: str = ""
    poll_interval_minutes: int = Field(DEFAULT_POLL_INTERVAL_MINUTES, ge=1, le=1440)
    enabled: bool = True
    page_type: str = "statuspage_v2"

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        if v not in CATEGORIES:
            return "Other"
        return v

    @field_validator("api_url")
    @classmethod
    def validate_api_url(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("http"):
            raise ValueError("api_url must start with http:// or https://")
        return v

    @field_validator("page_type")
    @classmethod
    def validate_page_type(cls, v: str) -> str:
        return v if v in PAGE_TYPES else "statuspage_v2"


class ServiceUpdate(ServiceCreate):
    pass


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Connecting to database …")
    pool = await database.create_pool(DATABASE_URL)
    await database.init_schema(pool)
    await database.run_migrations(pool)
    await database.seed_default_services(pool, DEFAULT_SERVICES)
    app.state.pool = pool

    logger.info("Starting background scheduler …")
    scheduler = sched_module.create_scheduler(pool, DEFAULT_POLL_INTERVAL_MINUTES)
    scheduler.start()
    app.state.scheduler = scheduler

    # Kick off an immediate first-poll in the background (non-blocking)
    asyncio.create_task(sched_module.run_full_refresh(pool))

    logger.info("SaaS Incident Monitor started — http://%s:%s", APP_HOST, APP_PORT)

    yield  # App is running

    # Shutdown
    logger.info("Shutting down scheduler …")
    scheduler.shutdown(wait=False)
    await pool.close()
    logger.info("Goodbye.")


# ── App factory ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Central SaaS Incident Monitor",
    version="1.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="static"), name="static")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pool():
    return app.state.pool


# ── Dashboard data endpoints ──────────────────────────────────────────────────

@app.get("/ping", include_in_schema=False)
async def ping():
    """Lightweight liveness probe — no DB required."""
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
async def root():
    return FileResponse("static/index.html")


@app.get("/services", include_in_schema=False)
async def services_page():
    return FileResponse("static/services.html")


@app.get("/api/services")
async def get_services():
    """All services (enabled + disabled) sorted by name — used by dashboard and drawer."""
    services = await database.get_all_services(_pool())
    return services


@app.get("/api/incidents")
async def get_incidents(active: bool = True, limit: int = 100):
    """Incidents sorted by severity ASC, started_at DESC."""
    if active:
        return await database.get_active_incidents(_pool())
    return await database.get_recent_incidents(_pool(), limit=min(limit, 200))


@app.get("/api/health")
async def get_health():
    """Overall health score, active incident count, and latest AI narrative."""
    services = await database.get_all_services(_pool())
    active = await database.get_active_incidents(_pool())
    ai = await database.get_latest_ai_analysis(_pool(), "global_health")

    overall_score = normalizer.compute_overall_health(services)
    enabled = [s for s in services if s.get("enabled", True)]

    return {
        "overall_score": overall_score,
        "active_incident_count": len(active),
        "total_services": len(services),
        "enabled_services": len(enabled),
        "ai_analysis": ai.get("content", "") if ai else "",
        "ai_analysis_at": ai.get("created_at", "") if ai else "",
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/refresh")
async def refresh():
    """Force-fetch all enabled services immediately."""
    count = await sched_module.run_full_refresh(_pool())
    return {
        "status": "ok",
        "services_fetched": count,
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Service Registry CRUD ─────────────────────────────────────────────────────

@app.post("/api/services", status_code=201)
async def create_service(body: ServiceCreate):
    service = await database.create_service(_pool(), body.model_dump())
    return service


@app.put("/api/services/{slug}")
async def update_service(slug: str, body: ServiceUpdate):
    service = await database.update_service(_pool(), slug, body.model_dump())
    if not service:
        raise HTTPException(status_code=404, detail=f"Service '{slug}' not found")
    return service


@app.delete("/api/services/{slug}", status_code=204)
async def delete_service(slug: str):
    deleted = await database.delete_service(_pool(), slug)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Service '{slug}' not found")


@app.patch("/api/services/{slug}/toggle")
async def toggle_service(slug: str):
    service = await database.toggle_service(_pool(), slug)
    if not service:
        raise HTTPException(status_code=404, detail=f"Service '{slug}' not found")
    return service


@app.get("/api/categories")
async def get_categories():
    return CATEGORIES


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host=APP_HOST,
        port=APP_PORT,
        reload=False,
        log_level="info",
    )
