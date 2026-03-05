"""asyncpg database pool, schema init, and all CRUD helpers."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

import asyncpg


# ── Schema ────────────────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS services (
    slug                    TEXT PRIMARY KEY,
    name                    TEXT NOT NULL,
    category                TEXT NOT NULL DEFAULT 'Other',
    website                 TEXT NOT NULL DEFAULT '',
    api_url                 TEXT NOT NULL,
    logo_url                TEXT DEFAULT '',
    poll_interval_minutes   INTEGER NOT NULL DEFAULT 5,
    page_type               TEXT NOT NULL DEFAULT 'statuspage_v2',
    enabled                 BOOLEAN NOT NULL DEFAULT TRUE,
    current_status          TEXT NOT NULL DEFAULT 'unknown',
    health_score            INTEGER NOT NULL DEFAULT 100,
    active_incident_count   INTEGER NOT NULL DEFAULT 0,
    last_checked            TIMESTAMPTZ,
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS incidents (
    id                  TEXT PRIMARY KEY,
    service_slug        TEXT NOT NULL REFERENCES services(slug) ON DELETE CASCADE,
    service_name        TEXT NOT NULL,
    service_category    TEXT NOT NULL,
    normalized_status   TEXT NOT NULL,
    severity            INTEGER NOT NULL,
    severity_label      TEXT NOT NULL,
    title               TEXT NOT NULL,
    description         TEXT DEFAULT '',
    started_at          TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ,
    resolved_at         TIMESTAMPTZ,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    components_affected JSONB NOT NULL DEFAULT '[]',
    updates             JSONB NOT NULL DEFAULT '[]',
    health_score        INTEGER NOT NULL DEFAULT 100,
    ai_summary          TEXT,
    ai_impact           TEXT,
    ai_analyzed_at      TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ai_analyses (
    id              BIGSERIAL PRIMARY KEY,
    analysis_type   TEXT NOT NULL DEFAULT 'global_health',
    content         TEXT NOT NULL,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_incidents_service  ON incidents(service_slug);
CREATE INDEX IF NOT EXISTS idx_incidents_active   ON incidents(is_active);
CREATE INDEX IF NOT EXISTS idx_incidents_severity ON incidents(severity);
CREATE INDEX IF NOT EXISTS idx_incidents_started  ON incidents(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_analyses_type   ON ai_analyses(analysis_type, created_at DESC);
"""


# ── Migrations ────────────────────────────────────────────────────────────────

MIGRATIONS_SQL = [
    "ALTER TABLE services ADD COLUMN IF NOT EXISTS page_type TEXT NOT NULL DEFAULT 'statuspage_v2';",
    # Fix existing Slack row to use the correct page_type and working API URL
    "UPDATE services SET page_type = 'slack', api_url = 'https://slack-status.com/api/v2.0.0/current' WHERE slug = 'slack' AND page_type = 'statuspage_v2';",
    # Fix Okta to use HTML type (API requires subscription)
    "UPDATE services SET page_type = 'html', api_url = 'https://status.okta.com/' WHERE slug = 'okta' AND api_url LIKE '%/api/v2/summary.json';",
    # Disable Microsoft 365 (no public API)
    "UPDATE services SET enabled = FALSE WHERE slug = 'office365';",
]


async def run_migrations(pool: asyncpg.Pool) -> None:
    """Apply all schema migrations idempotently (safe to run on every startup)."""
    async with pool.acquire() as conn:
        for sql in MIGRATIONS_SQL:
            await conn.execute(sql)


# ── Pool init ─────────────────────────────────────────────────────────────────

async def create_pool(dsn: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(dsn, min_size=2, max_size=10)


async def init_schema(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)


async def seed_default_services(pool: asyncpg.Pool, services: list[dict]) -> None:
    """Insert seed services only if the table is empty."""
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM services")
        if count > 0:
            return
        for svc in services:
            await conn.execute(
                """
                INSERT INTO services
                    (slug, name, category, website, api_url, logo_url, poll_interval_minutes, page_type)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                ON CONFLICT (slug) DO NOTHING
                """,
                svc["slug"],
                svc["name"],
                svc.get("category", "Other"),
                svc.get("website", ""),
                svc["api_url"],
                svc.get("logo_url", ""),
                svc.get("poll_interval_minutes", 5),
                svc.get("page_type", "statuspage_v2"),
            )


# ── Helper ───────────────────────────────────────────────────────────────────

def _row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
        elif isinstance(v, (list, dict)):
            pass  # already Python objects from JSONB
    return d


def slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "-", s)
    return s.strip("-")[:64]


# ── Services CRUD ─────────────────────────────────────────────────────────────

async def get_all_services(pool: asyncpg.Pool) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM services ORDER BY name ASC"
        )
    return [_row_to_dict(r) for r in rows]


async def get_enabled_services(pool: asyncpg.Pool) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM services WHERE enabled = TRUE ORDER BY name ASC"
        )
    return [_row_to_dict(r) for r in rows]


async def get_service(pool: asyncpg.Pool, slug: str) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM services WHERE slug = $1", slug)
    return _row_to_dict(row) if row else None


async def create_service(pool: asyncpg.Pool, data: dict) -> dict:
    slug = slugify(data["name"])
    # Ensure uniqueness
    async with pool.acquire() as conn:
        existing = await conn.fetchval("SELECT slug FROM services WHERE slug = $1", slug)
        if existing:
            slug = f"{slug}-{int(datetime.now(timezone.utc).timestamp())}"
        row = await conn.fetchrow(
            """
            INSERT INTO services
                (slug, name, category, website, api_url, logo_url, poll_interval_minutes, page_type, enabled)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            RETURNING *
            """,
            slug,
            data["name"],
            data.get("category", "Other"),
            data.get("website", ""),
            data["api_url"],
            data.get("logo_url", ""),
            data.get("poll_interval_minutes", 5),
            data.get("page_type", "statuspage_v2"),
            data.get("enabled", True),
        )
    return _row_to_dict(row)


async def update_service(pool: asyncpg.Pool, slug: str, data: dict) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE services SET
                name                  = $2,
                category              = $3,
                website               = $4,
                api_url               = $5,
                logo_url              = $6,
                poll_interval_minutes = $7,
                page_type             = $8,
                enabled               = $9,
                updated_at            = NOW()
            WHERE slug = $1
            RETURNING *
            """,
            slug,
            data["name"],
            data.get("category", "Other"),
            data.get("website", ""),
            data["api_url"],
            data.get("logo_url", ""),
            data.get("poll_interval_minutes", 5),
            data.get("page_type", "statuspage_v2"),
            data.get("enabled", True),
        )
    return _row_to_dict(row) if row else None


async def delete_service(pool: asyncpg.Pool, slug: str) -> bool:
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM services WHERE slug = $1", slug)
    return result.endswith("1")


async def toggle_service(pool: asyncpg.Pool, slug: str) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE services
            SET enabled = NOT enabled, updated_at = NOW()
            WHERE slug = $1
            RETURNING *
            """,
            slug,
        )
    return _row_to_dict(row) if row else None


async def update_service_status(
    pool: asyncpg.Pool,
    slug: str,
    status: str,
    health_score: int,
    active_count: int,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE services SET
                current_status        = $2,
                health_score          = $3,
                active_incident_count = $4,
                last_checked          = NOW(),
                updated_at            = NOW()
            WHERE slug = $1
            """,
            slug, status, health_score, active_count,
        )


async def get_due_services(pool: asyncpg.Pool) -> list[dict]:
    """Return enabled services whose last_checked is past their poll interval."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM services
            WHERE enabled = TRUE
            AND (
                last_checked IS NULL
                OR last_checked < NOW() - (poll_interval_minutes || ' minutes')::INTERVAL
            )
            ORDER BY last_checked ASC NULLS FIRST
            """
        )
    return [_row_to_dict(r) for r in rows]


# ── Incidents ─────────────────────────────────────────────────────────────────

async def upsert_incident(pool: asyncpg.Pool, inc: dict) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO incidents (
                id, service_slug, service_name, service_category,
                normalized_status, severity, severity_label,
                title, description,
                started_at, updated_at, resolved_at,
                is_active, components_affected, updates, health_score
            ) VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16
            )
            ON CONFLICT (id) DO UPDATE SET
                normalized_status   = EXCLUDED.normalized_status,
                severity            = EXCLUDED.severity,
                severity_label      = EXCLUDED.severity_label,
                title               = EXCLUDED.title,
                description         = EXCLUDED.description,
                updated_at          = EXCLUDED.updated_at,
                resolved_at         = EXCLUDED.resolved_at,
                is_active           = EXCLUDED.is_active,
                components_affected = EXCLUDED.components_affected,
                updates             = EXCLUDED.updates,
                health_score        = EXCLUDED.health_score
            """,
            inc["id"],
            inc["service_slug"],
            inc["service_name"],
            inc["service_category"],
            inc["normalized_status"],
            inc["severity"],
            inc["severity_label"],
            inc["title"],
            inc.get("description", ""),
            _parse_dt(inc.get("started_at")),
            _parse_dt(inc.get("updated_at")),
            _parse_dt(inc.get("resolved_at")),
            inc.get("is_active", True),
            json.dumps(inc.get("components_affected", [])),
            json.dumps(inc.get("updates", [])),
            inc.get("health_score", 100),
        )


def _parse_dt(val: str | None) -> datetime | None:
    if not val:
        return None
    try:
        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


async def get_active_incidents(pool: asyncpg.Pool) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT i.*, s.logo_url
            FROM incidents i
            JOIN services s ON s.slug = i.service_slug
            WHERE i.is_active = TRUE
            ORDER BY i.severity ASC, i.started_at DESC
            """
        )
    return [_row_to_dict(r) for r in rows]


async def get_recent_incidents(pool: asyncpg.Pool, limit: int = 50) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT i.*, s.logo_url
            FROM incidents i
            JOIN services s ON s.slug = i.service_slug
            ORDER BY i.started_at DESC
            LIMIT $1
            """,
            limit,
        )
    return [_row_to_dict(r) for r in rows]


async def needs_ai_analysis(pool: asyncpg.Pool, incident_id: str) -> bool:
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT ai_summary IS NULL FROM incidents WHERE id = $1",
            incident_id,
        )
    return bool(val)


async def update_incident_ai(
    pool: asyncpg.Pool,
    incident_id: str,
    summary: str,
    impact: str,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE incidents SET
                ai_summary     = $2,
                ai_impact      = $3,
                ai_analyzed_at = NOW()
            WHERE id = $1
            """,
            incident_id, summary, impact,
        )


# ── AI analyses ───────────────────────────────────────────────────────────────

async def save_ai_analysis(
    pool: asyncpg.Pool,
    analysis_type: str,
    content: str,
    metadata: dict,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO ai_analyses (analysis_type, content, metadata)
            VALUES ($1, $2, $3)
            """,
            analysis_type,
            content,
            json.dumps(metadata),
        )


async def get_latest_ai_analysis(
    pool: asyncpg.Pool,
    analysis_type: str,
) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM ai_analyses
            WHERE analysis_type = $1
            ORDER BY created_at DESC
            LIMIT 1
            """,
            analysis_type,
        )
    return _row_to_dict(row) if row else None
