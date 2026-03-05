"""Convert raw Statuspage v2 / HTML-extracted data to normalized dataclasses."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any

from config import (
    INCIDENT_STATUS_MAP,
    SEVERITY_MAP,
    STATUS_MAP,
)


@dataclass
class NormalizedService:
    slug: str
    name: str
    category: str
    website: str
    api_url: str
    logo_url: str
    poll_interval_minutes: int
    enabled: bool
    current_status: str
    health_score: int
    active_incident_count: int


@dataclass
class NormalizedIncident:
    id: str
    service_slug: str
    service_name: str
    service_category: str
    normalized_status: str
    severity: int
    severity_label: str
    title: str
    description: str
    started_at: str | None
    updated_at: str | None
    resolved_at: str | None
    is_active: bool
    components_affected: list[str] = field(default_factory=list)
    updates: list[dict] = field(default_factory=list)
    health_score: int = 100


def normalize_response(
    raw: dict[str, Any],
    service_cfg: dict,
) -> tuple[NormalizedService, list[NormalizedIncident]]:
    """Parse a Statuspage v2 summary JSON into a NormalizedService + incidents."""

    # ── Page-level status ────────────────────────────────────────────────────
    page_indicator = (
        raw.get("status", {}).get("indicator", "none") or "none"
    ).lower()
    normalized_status, health_score = STATUS_MAP.get(
        page_indicator, ("unknown", 50)
    )

    # ── Active incidents ─────────────────────────────────────────────────────
    raw_incidents: list[dict] = raw.get("incidents", [])
    # Also surface scheduled maintenance
    raw_maintenance: list[dict] = raw.get("scheduled_maintenances", [])

    normalized_incidents: list[NormalizedIncident] = []

    for inc in raw_incidents:
        ni = _normalize_incident(inc, service_cfg)
        if ni:
            normalized_incidents.append(ni)

    for maint in raw_maintenance:
        ni = _normalize_maintenance(maint, service_cfg)
        if ni:
            normalized_incidents.append(ni)

    active_count = sum(1 for ni in normalized_incidents if ni.is_active)

    svc = NormalizedService(
        slug=service_cfg["slug"],
        name=service_cfg["name"],
        category=service_cfg.get("category", "Other"),
        website=service_cfg.get("website", ""),
        api_url=service_cfg["api_url"],
        logo_url=service_cfg.get("logo_url", ""),
        poll_interval_minutes=service_cfg.get("poll_interval_minutes", 5),
        enabled=service_cfg.get("enabled", True),
        current_status=normalized_status,
        health_score=health_score,
        active_incident_count=active_count,
    )

    return svc, normalized_incidents


def _normalize_incident(
    raw: dict[str, Any],
    service_cfg: dict,
) -> NormalizedIncident | None:
    if not raw.get("id"):
        return None

    incident_id = raw["id"]
    slug = service_cfg["slug"]

    raw_status = (raw.get("status") or "investigating").lower()
    normalized_status = INCIDENT_STATUS_MAP.get(raw_status, "investigating")

    raw_impact = (raw.get("impact") or "none").lower()
    severity, severity_label = SEVERITY_MAP.get(raw_impact, (4, "Info"))

    is_resolved = raw.get("resolved_at") is not None
    is_active = not is_resolved

    # Re-map status if resolved
    if is_resolved:
        normalized_status = "resolved"

    # Health score per incident
    health_score = {
        1: 0,   # Critical
        2: 30,  # Major
        3: 70,  # Minor
        4: 90,  # Info
    }.get(severity, 90)

    # Components affected
    components: list[str] = [
        c.get("name", "") for c in raw.get("components", []) if c.get("name")
    ]

    # Update timeline
    updates: list[dict] = [
        {
            "time": u.get("created_at") or u.get("display_at", ""),
            "status": u.get("status", ""),
            "body": u.get("body", ""),
        }
        for u in raw.get("incident_updates", [])
    ]

    return NormalizedIncident(
        id=f"{slug}_{incident_id}",
        service_slug=slug,
        service_name=service_cfg["name"],
        service_category=service_cfg.get("category", "Other"),
        normalized_status=normalized_status,
        severity=severity,
        severity_label=severity_label,
        title=raw.get("name", "Untitled Incident"),
        description=_first_update_body(raw),
        started_at=raw.get("created_at"),
        updated_at=raw.get("updated_at"),
        resolved_at=raw.get("resolved_at"),
        is_active=is_active,
        components_affected=components,
        updates=updates,
        health_score=health_score,
    )


def _normalize_maintenance(
    raw: dict[str, Any],
    service_cfg: dict,
) -> NormalizedIncident | None:
    if not raw.get("id"):
        return None

    incident_id = raw["id"]
    slug = service_cfg["slug"]

    raw_status = (raw.get("status") or "scheduled").lower()
    normalized_status = INCIDENT_STATUS_MAP.get(raw_status, "maintenance")

    is_completed = raw.get("resolved_at") is not None or raw_status == "completed"
    is_active = not is_completed

    components: list[str] = [
        c.get("name", "") for c in raw.get("components", []) if c.get("name")
    ]
    updates: list[dict] = [
        {
            "time": u.get("created_at") or u.get("display_at", ""),
            "status": u.get("status", ""),
            "body": u.get("body", ""),
        }
        for u in raw.get("incident_updates", [])
    ]

    return NormalizedIncident(
        id=f"{slug}_{incident_id}",
        service_slug=slug,
        service_name=service_cfg["name"],
        service_category=service_cfg.get("category", "Other"),
        normalized_status=normalized_status,
        severity=4,
        severity_label="Maintenance",
        title=raw.get("name", "Scheduled Maintenance"),
        description=_first_update_body(raw),
        started_at=raw.get("scheduled_for") or raw.get("created_at"),
        updated_at=raw.get("updated_at"),
        resolved_at=raw.get("resolved_at"),
        is_active=is_active,
        components_affected=components,
        updates=updates,
        health_score=85,
    )


def _first_update_body(raw: dict) -> str:
    updates = raw.get("incident_updates", [])
    if updates:
        return updates[-1].get("body", "")  # oldest update = initial description
    return ""


def compute_overall_health(services: list[dict]) -> int:
    """Weighted average health score for all enabled services."""
    enabled = [s for s in services if s.get("enabled", True)]
    if not enabled:
        return 100
    total = sum(s.get("health_score", 100) for s in enabled)
    return round(total / len(enabled))


def incident_to_dict(ni: NormalizedIncident) -> dict:
    return asdict(ni)


# ── Slack custom normalizer ───────────────────────────────────────────────────

_SLACK_STATUS_MAP: dict[str, tuple[str, int]] = {
    "ok":                 ("operational", 100),
    "active":             ("degraded",    70),
    "service disruption": ("degraded",    70),
    "service outage":     ("outage",      30),
    "maintenance":        ("maintenance", 85),
}

_SLACK_SEVERITY_MAP: dict[str, tuple[int, str]] = {
    "critical": (1, "Critical"),
    "major":    (2, "Major"),
    "minor":    (3, "Minor"),
}


def normalize_slack_response(
    raw: dict[str, Any],
    service_cfg: dict,
) -> tuple[NormalizedService, list[NormalizedIncident]]:
    """Parse Slack's custom status API (v2.0.0/current) into normalized dataclasses."""
    raw_status = (raw.get("status") or "ok").lower()
    normalized_status, health_score = _SLACK_STATUS_MAP.get(raw_status, ("unknown", 50))

    raw_incidents: list[dict] = raw.get("active_incidents") or []
    normalized_incidents = [
        ni
        for inc in raw_incidents
        if (ni := _normalize_slack_incident(inc, service_cfg)) is not None
    ]
    active_count = sum(1 for ni in normalized_incidents if ni.is_active)

    svc = NormalizedService(
        slug=service_cfg["slug"],
        name=service_cfg["name"],
        category=service_cfg.get("category", "Other"),
        website=service_cfg.get("website", ""),
        api_url=service_cfg["api_url"],
        logo_url=service_cfg.get("logo_url", ""),
        poll_interval_minutes=service_cfg.get("poll_interval_minutes", 5),
        enabled=service_cfg.get("enabled", True),
        current_status=normalized_status,
        health_score=health_score,
        active_incident_count=active_count,
    )
    return svc, normalized_incidents


def _normalize_slack_incident(
    raw: dict[str, Any],
    service_cfg: dict,
) -> NormalizedIncident | None:
    slug = service_cfg["slug"]
    incident_id = str(raw.get("id") or "")
    if not incident_id:
        return None

    raw_sev = (raw.get("severity") or "minor").lower()
    severity, severity_label = _SLACK_SEVERITY_MAP.get(raw_sev, (3, "Minor"))
    health_score = {1: 0, 2: 30, 3: 70}.get(severity, 70)

    notes: list[dict] = raw.get("notes") or []
    description = notes[0].get("body", "") if notes else ""
    updates = [
        {"time": n.get("date_created", ""), "status": "update", "body": n.get("body", "")}
        for n in notes
    ]

    return NormalizedIncident(
        id=f"{slug}_{incident_id}",
        service_slug=slug,
        service_name=service_cfg["name"],
        service_category=service_cfg.get("category", "Other"),
        normalized_status="investigating",
        severity=severity,
        severity_label=severity_label,
        title=raw.get("title", "Slack Incident"),
        description=description,
        started_at=raw.get("date_created"),
        updated_at=raw.get("date_updated"),
        resolved_at=None,
        is_active=True,
        components_affected=raw.get("services") or [],
        updates=updates,
        health_score=health_score,
    )


# ── HTML-extracted normalizers ────────────────────────────────────────────────

def normalize_html_response(
    extracted: dict[str, Any],
    service_cfg: dict,
) -> tuple[NormalizedService, list[NormalizedIncident]]:
    """Convert Claude's HTML extraction output to NormalizedService + incidents."""
    raw_status = (extracted.get("status") or "unknown").lower()
    normalized_status, health_score = STATUS_MAP.get(raw_status, ("unknown", 50))

    raw_incidents: list[dict] = extracted.get("incidents") or []
    normalized_incidents = [
        ni
        for inc in raw_incidents
        if (ni := _normalize_html_incident(inc, service_cfg)) is not None
    ]
    active_count = sum(1 for ni in normalized_incidents if ni.is_active)

    svc = NormalizedService(
        slug=service_cfg["slug"],
        name=service_cfg["name"],
        category=service_cfg.get("category", "Other"),
        website=service_cfg.get("website", ""),
        api_url=service_cfg["api_url"],
        logo_url=service_cfg.get("logo_url", ""),
        poll_interval_minutes=service_cfg.get("poll_interval_minutes", 5),
        enabled=service_cfg.get("enabled", True),
        current_status=normalized_status,
        health_score=health_score,
        active_incident_count=active_count,
    )
    return svc, normalized_incidents


def _normalize_html_incident(
    raw: dict[str, Any],
    service_cfg: dict,
) -> NormalizedIncident | None:
    title = raw.get("title") or "Untitled Incident"
    slug = service_cfg["slug"]
    # Deterministic ID — same title on next poll → upsert rather than duplicate row
    h = hashlib.md5(title.encode()).hexdigest()[:8]

    raw_sev = (raw.get("severity") or "minor").lower()
    severity, severity_label = SEVERITY_MAP.get(raw_sev, (3, "Minor"))
    health_score = {1: 0, 2: 30, 3: 70, 4: 90}.get(severity, 70)

    return NormalizedIncident(
        id=f"{slug}_html_{h}",
        service_slug=slug,
        service_name=service_cfg["name"],
        service_category=service_cfg.get("category", "Other"),
        normalized_status="investigating",
        severity=severity,
        severity_label=severity_label,
        title=title,
        description=raw.get("description", ""),
        started_at=raw.get("started_at"),
        updated_at=None,
        resolved_at=None,
        is_active=True,
        components_affected=raw.get("components_affected") or [],
        updates=[],
        health_score=health_score,
    )
