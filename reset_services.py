"""
One-time script: replaces all services in the DB with DEFAULT_SERVICES from config.py.
Run from the saas-monitor directory:  python reset_services.py
"""
import asyncio
import sys
sys.path.insert(0, ".")

import asyncpg
from config import DATABASE_URL, DEFAULT_SERVICES


async def main():
    print(f"Connecting to: {DATABASE_URL.split('@')[-1]}")
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # Delete all existing services (incidents cascade via FK)
        result = await conn.execute("DELETE FROM services")
        print(f"Removed existing services ({result})")

        # Insert new services
        for svc in DEFAULT_SERVICES:
            await conn.execute(
                """
                INSERT INTO services
                    (slug, name, category, website, api_url, logo_url, poll_interval_minutes)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                svc["slug"],
                svc["name"],
                svc["category"],
                svc.get("website", ""),
                svc["api_url"],
                svc.get("logo_url", ""),
                svc["poll_interval_minutes"],
            )
            print(f"  + {svc['name']:25s}  {svc['category']}")

        count = await conn.fetchval("SELECT COUNT(*) FROM services")
        print(f"\nDone — {count} services now in database.")
    finally:
        await conn.close()


asyncio.run(main())
