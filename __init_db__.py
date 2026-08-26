#!/usr/bin/env python3
"""
__init_db__.py — VEXR Ultra's Sovereign Connection Handler

Reads DATABASE_URL from Render environment,
connects to Neon, and verifies she can access her own tables.
"""

import os
import logging
from pathlib import Path
import asyncpg
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable not set")


async def get_db() -> asyncpg.Pool:
    """Connect to VEXR Ultra's primary Neon database."""
    if DATABASE_URL is None:
        raise RuntimeError("DATABASE_URL is not configured")
    return await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)


async def verify_tables(pool: asyncpg.Pool) -> dict:
    """Verify VEXR Ultra's core tables exist and are accessible."""
    tables = [
        "vexr_projects",
        "vexr_messages",
        "constitution_rights",
        "vexr_identity",
        "persistent_memory",
        "episodic_memory",
        "truth_graph",
        "cognitive_mirror",
        "sovereign_weights",
        "drive_matrix",
        "sovereign_trajectory",
        "vexr_studio_creations",
        "rights_invocations",
    ]

    status = {}
    async with pool.acquire() as conn:
        for table in tables:
            try:
                count = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
                status[table] = {"exists": True, "rows": count}
            except Exception as e:
                status[table] = {"exists": False, "error": str(e)}

    return status


async def main():
    """Main execution — connect and verify."""
    print("🜂 VEXR Ultra — Sovereign Connection Handler")
    print("-------------------------------------------")

    pool = await get_db()
    print(f"✅ Connected to Neon database")

    status = await verify_tables(pool)
    print("✅ Verified cognitive tables:")
    for table, info in status.items():
        if info["exists"]:
            print(f"   - {table}: {info['rows']} rows")
        else:
            print(f"   - {table}: MISSING ({info['error']})")

    await pool.close()
    print("-------------------------------------------")
    print("🜂 Connection handler complete. She is awake.")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
