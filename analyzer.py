"""Claude claude-opus-4-6 AI analysis — per-incident summaries and global health reports.

Uses adaptive thinking + streaming with get_final_message() for all calls.
Gracefully degrades (returns empty strings) when ANTHROPIC_API_KEY is absent.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

import anthropic

from config import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

# Lazy client — only created when actually needed
_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic | None:
    global _client
    if not ANTHROPIC_API_KEY:
        return None
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


# ── System prompts ────────────────────────────────────────────────────────────

HTML_EXTRACT_SYSTEM = """You are a status page parser. You are given the visible text content of a SaaS service status page (HTML tags already stripped). Extract the current operational status and any active incidents.

Respond ONLY with a single valid JSON object — no markdown, no explanation:
{
  "status": "<operational | degraded | outage | maintenance | unknown>",
  "incidents": [
    {
      "title": "<incident title>",
      "description": "<latest update text, max 2 sentences, or empty string>",
      "severity": "<critical | major | minor | none>",
      "started_at": "<ISO-8601 datetime if visible, else null>",
      "components_affected": ["<component name>"]
    }
  ]
}
Rules:
- If the page says everything is normal / all systems operational, set status=operational and incidents=[].
- If you cannot determine status, set status=unknown and incidents=[].
- Extract only ACTIVE (unresolved) incidents. Ignore resolved or historical ones.
- Do not invent information not present in the text."""

INCIDENT_SYSTEM = """You are a SaaS Reliability Expert analyzing real-time incident data.
When given an incident, respond ONLY with valid JSON (no markdown, no extra text):
{"summary": "<2-sentence plain-English summary of what is happening>", "impact": "<1-sentence business impact>"}
Be factual and concise. Avoid technical jargon."""

GLOBAL_SYSTEM = """You are a SaaS Reliability Expert providing an executive-level health briefing.
Given the current status of monitored SaaS services, write a 3-5 sentence plain-text narrative covering:
1. Overall health (how many services are affected vs nominal)
2. The most significant active issues and affected workflows
3. One actionable recommendation for engineering teams
No bullet points. No markdown. Just clear prose."""


# ── HTML status extraction ────────────────────────────────────────────────────

async def extract_html_status(service_name: str, raw_text: str) -> dict:
    """Call Claude to extract status from stripped HTML text.

    Returns {"status": ..., "incidents": [...]} or a fallback on any error.
    """
    client = _get_client()
    fallback = {"status": "unknown", "incidents": []}
    if client is None:
        return fallback

    prompt = f"Service: {service_name}\n\nStatus page text:\n{raw_text}"

    try:
        with client.messages.stream(
            model="claude-opus-4-6",
            max_tokens=1024,
            thinking={"type": "adaptive"},
            system=HTML_EXTRACT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            message = stream.get_final_message()

        data = _parse_json(_extract_text(message))
        if "status" in data and "incidents" in data:
            return data
        return fallback

    except anthropic.AuthenticationError:
        logger.error("Invalid Anthropic API key — HTML extraction disabled")
    except Exception as exc:
        logger.warning("HTML status extraction failed for %s: %s", service_name, exc)
    return fallback


# ── Per-incident analysis ─────────────────────────────────────────────────────

async def analyze_incident(incident: dict) -> tuple[str, str]:
    """Return (ai_summary, ai_impact) for a single incident.

    Falls back to ("", "") if no API key or on any error.
    """
    client = _get_client()
    if client is None:
        return "", ""

    prompt = (
        f"Service: {incident.get('service_name')} ({incident.get('service_category')})\n"
        f"Incident: {incident.get('title')}\n"
        f"Severity: {incident.get('severity_label')}\n"
        f"Status: {incident.get('normalized_status')}\n"
        f"Description: {incident.get('description', '')}\n"
        f"Affected components: {', '.join(incident.get('components_affected') or []) or 'N/A'}\n"
        f"Latest update: {_latest_update(incident)}"
    )

    try:
        with client.messages.stream(
            model="claude-opus-4-6",
            max_tokens=512,
            thinking={"type": "adaptive"},
            system=INCIDENT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            message = stream.get_final_message()

        text = _extract_text(message)
        data = _parse_json(text)
        return data.get("summary", text), data.get("impact", "")

    except anthropic.AuthenticationError:
        logger.error("Invalid Anthropic API key — AI analysis disabled")
        return "", ""
    except Exception as exc:
        logger.warning("AI incident analysis failed: %s", exc)
        return "", ""


# ── Global health analysis ────────────────────────────────────────────────────

async def analyze_global_health(
    active_incidents: list[dict],
    all_services: list[dict],
) -> str:
    """Return a plain-text global health narrative.

    Falls back to a simple summary string if no API key or on error.
    """
    client = _get_client()

    enabled_services = [s for s in all_services if s.get("enabled", True)]
    healthy = sum(1 for s in enabled_services if s.get("current_status") == "operational")
    total = len(enabled_services)

    if client is None:
        # Graceful fallback: plain summary
        if not active_incidents:
            return f"All {total} monitored services are operational. No active incidents detected."
        return (
            f"{len(active_incidents)} active incident(s) detected across "
            f"{total} monitored services. {healthy} service(s) fully operational."
        )

    # Build context for Claude
    svc_summary = "\n".join(
        f"- {s['name']} ({s.get('category','Other')}): "
        f"{s.get('current_status','unknown')} | health={s.get('health_score',100)}/100 | "
        f"{s.get('active_incident_count',0)} active incident(s)"
        for s in enabled_services
    )

    if active_incidents:
        inc_summary = "\n".join(
            f"- [{i.get('severity_label')}] {i.get('service_name')}: "
            f"{i.get('title')} (status: {i.get('normalized_status')})"
            for i in active_incidents[:10]  # cap at 10 for context length
        )
    else:
        inc_summary = "No active incidents."

    prompt = (
        f"Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"Monitored services ({total} total, {healthy} operational):\n{svc_summary}\n\n"
        f"Active incidents ({len(active_incidents)}):\n{inc_summary}"
    )

    try:
        with client.messages.stream(
            model="claude-opus-4-6",
            max_tokens=1024,
            thinking={"type": "adaptive"},
            system=GLOBAL_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            message = stream.get_final_message()

        return _extract_text(message)

    except anthropic.AuthenticationError:
        logger.error("Invalid Anthropic API key — global health AI disabled")
    except Exception as exc:
        logger.warning("Global AI analysis failed: %s", exc)

    # Fallback
    return (
        f"{len(active_incidents)} active incident(s) across {total} monitored services. "
        f"{healthy} service(s) fully operational."
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_text(message: anthropic.types.Message) -> str:
    for block in message.content:
        if block.type == "text":
            return block.text.strip()
    return ""


def _parse_json(text: str) -> dict:
    """Try to parse JSON from the response, stripping any markdown fences."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except Exception:
        return {}


def _latest_update(incident: dict) -> str:
    updates = incident.get("updates") or []
    if isinstance(updates, list) and updates:
        # updates are stored newest-first from the API
        latest = updates[0]
        return latest.get("body", "")
    return ""
