"""Service registry seed data, status/severity mappings, and app constants."""

import os

# ── Environment ──────────────────────────────────────────────────────────────

_raw_db_url = os.getenv(
    "DATABASE_URL",
    "postgresql://monitor:monitor_secret@localhost:5432/saas_monitor",
)
# Railway (and some other hosts) provide postgres:// — asyncpg requires postgresql://
DATABASE_URL = _raw_db_url.replace("postgres://", "postgresql://", 1) if _raw_db_url.startswith("postgres://") else _raw_db_url
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DEFAULT_POLL_INTERVAL_MINUTES = int(os.getenv("DEFAULT_POLL_INTERVAL_MINUTES", "5"))
AI_GLOBAL_REPORT_INTERVAL_MINUTES = int(os.getenv("AI_GLOBAL_REPORT_INTERVAL_MINUTES", "15"))
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "8000"))

# ── Valid categories ──────────────────────────────────────────────────────────

CATEGORIES = [
    "CDN",
    "Monitoring",
    "Communication",
    "Payments",
    "Development",
    "Storage",
    "CRM",
    "Security",
    "Email",
    "Infrastructure",
    "Support",
    "Other",
]

# ── Status/severity normalization maps ───────────────────────────────────────

# Statuspage page-level indicator → (normalized_status, health_score 0-100)
STATUS_MAP: dict[str, tuple[str, int]] = {
    "none":        ("operational", 100),
    "minor":       ("degraded",    70),
    "major":       ("outage",      30),
    "critical":    ("outage",      0),
    "maintenance": ("maintenance", 85),
}

# Statuspage incident impact → (severity int, label)
SEVERITY_MAP: dict[str, tuple[int, str]] = {
    "critical":    (1, "Critical"),
    "major":       (2, "Major"),
    "minor":       (3, "Minor"),
    "none":        (4, "Info"),
    "maintenance": (4, "Maintenance"),
}

# Incident status → normalized status
INCIDENT_STATUS_MAP: dict[str, str] = {
    "investigating": "investigating",
    "identified":    "investigating",
    "monitoring":    "monitoring",
    "resolved":      "resolved",
    "scheduled":     "maintenance",
    "in_progress":   "maintenance",
    "verifying":     "monitoring",
    "completed":     "resolved",
    "postmortem":    "resolved",
}

# Severity colour for UI  (maps severity int → Tailwind colour name)
SEVERITY_COLORS: dict[int, str] = {
    1: "red",
    2: "orange",
    3: "yellow",
    4: "blue",
}

# ── Default 27 services (seeded once on first startup) ───────────────────────
# Services marked [custom] do not use Atlassian Statuspage v2 and will show
# "unknown" status until a compatible poller is added for their platform.

DEFAULT_SERVICES: list[dict] = [
    # ── Infrastructure ─────────────────────────────────────────────────────────
    {
        "slug": "sap-cloud",
        "name": "SAP for Me",
        "category": "Infrastructure",
        "website": "https://www.sap.com",
        "api_url": "https://status.me.sap.com/api/v2/summary.json",
        "logo_url": "https://www.sap.com/favicon.ico",
        "poll_interval_minutes": DEFAULT_POLL_INTERVAL_MINUTES,
    },
    # ── Communication ────────────────────────────────────────────────────────
    {
        "slug": "zoom",
        "name": "Zoom",
        "category": "Communication",
        "website": "https://zoom.us",
        "api_url": "https://www.zoomstatus.com/api/v2/summary.json",
        "logo_url": "https://st1.zoom.us/zoom.ico",
        "poll_interval_minutes": DEFAULT_POLL_INTERVAL_MINUTES,
    },
    {
        "slug": "slack",
        "name": "Slack",
        "category": "Communication",
        "website": "https://slack.com",
        "api_url": "https://slack-status.com/api/v2.0.0/current",
        "logo_url": "https://slack.com/favicon.ico",
        "poll_interval_minutes": DEFAULT_POLL_INTERVAL_MINUTES,
        "page_type": "slack",
    },
    {
        "slug": "nice-cxone",
        "name": "NICE CXone",
        "category": "Communication",
        "website": "https://www.nice.com",
        "api_url": "https://status.niceincontact.com/api/v2/summary.json",
        "logo_url": "https://www.nice.com/favicon.ico",
        "poll_interval_minutes": DEFAULT_POLL_INTERVAL_MINUTES,
    },
    {
        "slug": "office365",
        "name": "Microsoft 365",
        "category": "Communication",
        "website": "https://www.microsoft.com/microsoft-365",
        "api_url": "https://status.cloud.microsoft/",  # [no-public-api] requires Microsoft Admin Portal auth — disabled
        "logo_url": "https://www.microsoft.com/favicon.ico",
        "poll_interval_minutes": DEFAULT_POLL_INTERVAL_MINUTES,
        "enabled": False,
    },
    # ── CDN ───────────────────────────────────────────────────────────────────
    {
        "slug": "cloudflare",
        "name": "Cloudflare",
        "category": "CDN",
        "website": "https://www.cloudflare.com",
        "api_url": "https://www.cloudflarestatus.com/api/v2/summary.json",
        "logo_url": "https://www.cloudflare.com/favicon.ico",
        "poll_interval_minutes": DEFAULT_POLL_INTERVAL_MINUTES,
    },
    # ── Infrastructure ────────────────────────────────────────────────────────
    {
        "slug": "citrix",
        "name": "Citrix",
        "category": "Infrastructure",
        "website": "https://www.citrix.com",
        "api_url": "https://status.cloud.com/api/v2/summary.json",  # [custom] Citrix uses statushub
        "logo_url": "https://www.citrix.com/favicon.ico",
        "poll_interval_minutes": DEFAULT_POLL_INTERVAL_MINUTES,
    },
    {
        "slug": "nutanix",
        "name": "Nutanix",
        "category": "Infrastructure",
        "website": "https://www.nutanix.com",
        "api_url": "https://status.nutanix.com/api/v2/summary.json",
        "logo_url": "https://www.nutanix.com/favicon.ico",
        "poll_interval_minutes": DEFAULT_POLL_INTERVAL_MINUTES,
    },
    # ── Development ───────────────────────────────────────────────────────────
    {
        "slug": "github",
        "name": "GitHub",
        "category": "Development",
        "website": "https://github.com",
        "api_url": "https://www.githubstatus.com/api/v2/summary.json",
        "logo_url": "https://github.githubassets.com/favicons/favicon.png",
        "poll_interval_minutes": DEFAULT_POLL_INTERVAL_MINUTES,
    },
    {
        "slug": "jira",
        "name": "Jira",
        "category": "Development",
        "website": "https://www.atlassian.com/software/jira",
        "api_url": "https://jira-software.status.atlassian.com/api/v2/summary.json",
        "logo_url": "https://wac-cdn.atlassian.com/assets/img/favicons/atlassian/favicon.png",
        "poll_interval_minutes": DEFAULT_POLL_INTERVAL_MINUTES,
    },
    {
        "slug": "confluence",
        "name": "Confluence",
        "category": "Development",
        "website": "https://www.atlassian.com/software/confluence",
        "api_url": "https://confluence.status.atlassian.com/api/v2/summary.json",
        "logo_url": "https://wac-cdn.atlassian.com/assets/img/favicons/atlassian/favicon.png",
        "poll_interval_minutes": DEFAULT_POLL_INTERVAL_MINUTES,
    },
    {
        "slug": "databricks",
        "name": "Databricks",
        "category": "Development",
        "website": "https://www.databricks.com",
        "api_url": "https://status.databricks.com/api/v2/summary.json",  # [custom] uses Status.io
        "logo_url": "https://www.databricks.com/favicon.ico",
        "poll_interval_minutes": DEFAULT_POLL_INTERVAL_MINUTES,
    },
    # ── Storage ───────────────────────────────────────────────────────────────
    {
        "slug": "box",
        "name": "Box",
        "category": "Storage",
        "website": "https://www.box.com",
        "api_url": "https://status.box.com/api/v2/summary.json",
        "logo_url": "https://www.box.com/favicon.ico",
        "poll_interval_minutes": DEFAULT_POLL_INTERVAL_MINUTES,
    },
    {
        "slug": "snowflake",
        "name": "Snowflake",
        "category": "Storage",
        "website": "https://www.snowflake.com",
        "api_url": "https://status.snowflake.com/api/v2/summary.json",
        "logo_url": "https://www.snowflake.com/favicon.ico",
        "poll_interval_minutes": DEFAULT_POLL_INTERVAL_MINUTES,
    },
    # ── CRM ───────────────────────────────────────────────────────────────────
    {
        "slug": "salesforce",
        "name": "Salesforce",
        "category": "CRM",
        "website": "https://www.salesforce.com",
        "api_url": "https://status.salesforce.com/api/v2/summary.json",  # [custom] Salesforce Trust API
        "logo_url": "https://www.salesforce.com/favicon.ico",
        "poll_interval_minutes": DEFAULT_POLL_INTERVAL_MINUTES,
    },
    {
        "slug": "conga",
        "name": "Conga",
        "category": "CRM",
        "website": "https://conga.com",
        "api_url": "https://status.conga.com/api/v2/summary.json",
        "logo_url": "https://conga.com/favicon.ico",
        "poll_interval_minutes": DEFAULT_POLL_INTERVAL_MINUTES,
    },
    # ── Security ──────────────────────────────────────────────────────────────
    {
        "slug": "okta",
        "name": "Okta",
        "category": "Security",
        "website": "https://www.okta.com",
        "api_url": "https://status.okta.com/",  # [custom] Salesforce-based page, API requires auth subscription
        "logo_url": "https://www.okta.com/favicon.ico",
        "poll_interval_minutes": DEFAULT_POLL_INTERVAL_MINUTES,
        "page_type": "html",
    },
    {
        "slug": "infoblox",
        "name": "Infoblox",
        "category": "Security",
        "website": "https://www.infoblox.com",
        "api_url": "https://status.infoblox.com/api/v2/summary.json",
        "logo_url": "https://www.infoblox.com/favicon.ico",
        "poll_interval_minutes": DEFAULT_POLL_INTERVAL_MINUTES,
    },
    {
        "slug": "jamf",
        "name": "Jamf",
        "category": "Security",
        "website": "https://www.jamf.com",
        "api_url": "https://status.jamf.com/api/v2/summary.json",
        "logo_url": "https://www.jamf.com/favicon.ico",
        "poll_interval_minutes": DEFAULT_POLL_INTERVAL_MINUTES,
    },
    {
        "slug": "kenna-security",
        "name": "Kenna Security",
        "category": "Security",
        "website": "https://www.cisco.com/site/us/en/products/security/vulnerability-management/index.html",
        "api_url": "https://status.kennasecurity.com/api/v2/summary.json",
        "logo_url": "https://www.cisco.com/favicon.ico",
        "poll_interval_minutes": DEFAULT_POLL_INTERVAL_MINUTES,
    },
    # ── Monitoring ────────────────────────────────────────────────────────────
    {
        "slug": "logicmonitor",
        "name": "LogicMonitor",
        "category": "Monitoring",
        "website": "https://www.logicmonitor.com",
        "api_url": "https://status.logicmonitor.com/api/v2/summary.json",
        "logo_url": "https://www.logicmonitor.com/favicon.ico",
        "poll_interval_minutes": DEFAULT_POLL_INTERVAL_MINUTES,
    },
    # ── Other ─────────────────────────────────────────────────────────────────
    {
        "slug": "anaplan",
        "name": "Anaplan",
        "category": "Other",
        "website": "https://www.anaplan.com",
        "api_url": "https://status.anaplan.com/api/v2/summary.json",
        "logo_url": "https://www.anaplan.com/favicon.ico",
        "poll_interval_minutes": DEFAULT_POLL_INTERVAL_MINUTES,
    },
    {
        "slug": "archibus",
        "name": "Archibus",
        "category": "Other",
        "website": "https://eptura.com/our-platform/archibus/",
        "api_url": "https://status.eptura.com/api/v2/summary.json",
        "logo_url": "https://eptura.com/favicon.ico",
        "poll_interval_minutes": DEFAULT_POLL_INTERVAL_MINUTES,
    },
    {
        "slug": "kaltura",
        "name": "Kaltura",
        "category": "Other",
        "website": "https://corp.kaltura.com",
        "api_url": "https://status.kaltura.com/api/v2/summary.json",
        "logo_url": "https://corp.kaltura.com/favicon.ico",
        "poll_interval_minutes": DEFAULT_POLL_INTERVAL_MINUTES,
    },
    {
        "slug": "lucid",
        "name": "Lucid",
        "category": "Other",
        "website": "https://lucid.co",
        "api_url": "https://status.lucid.co/api/v2/summary.json",
        "logo_url": "https://lucid.co/favicon.ico",
        "poll_interval_minutes": DEFAULT_POLL_INTERVAL_MINUTES,
    },
    {
        "slug": "qualtrics",
        "name": "Qualtrics",
        "category": "Other",
        "website": "https://www.qualtrics.com",
        "api_url": "https://status.qualtrics.com/api/v2/summary.json",
        "logo_url": "https://www.qualtrics.com/favicon.ico",
        "poll_interval_minutes": DEFAULT_POLL_INTERVAL_MINUTES,
    },
    {
        "slug": "smartsheet",
        "name": "Smartsheet",
        "category": "Other",
        "website": "https://www.smartsheet.com",
        "api_url": "https://status.smartsheet.com/api/v2/summary.json",
        "logo_url": "https://www.smartsheet.com/favicon.ico",
        "poll_interval_minutes": DEFAULT_POLL_INTERVAL_MINUTES,
    },
    {
        "slug": "workday",
        "name": "Workday",
        "category": "Other",
        "website": "https://www.workday.com",
        "api_url": "https://status.workday.com/api/v2/summary.json",  # [custom] redirects to community portal
        "logo_url": "https://www.workday.com/favicon.ico",
        "poll_interval_minutes": DEFAULT_POLL_INTERVAL_MINUTES,
    },
]
