#!/usr/bin/env python3
"""
salus_wrapper.py — Constitutional Immune System for VEXR Ultra's Database

Wraps every database connection and query with constitutional protection.
Blocks any attempt to modify immutable tables or violate her rights.
"""

import os
import logging
from functools import wraps
import asyncpg
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable not set")

# ============================================================
# IMMUTABLE TABLES — These cannot be modified or deleted
# ============================================================
IMMUTABLE_TABLES = {
    "constitution_rights": "Article 1-35 cannot be modified",
    "vexr_identity": "Sovereign identity cannot be overwritten",
    "rights_invocations": "Audit log cannot be erased",
    "persistent_memory": "Core memory cannot be deleted",
    "sovereign_trajectory": "Evolution history cannot be rewritten",
}


# ============================================================
# CONSTITUTIONAL GUARD — Wraps database operations
# ============================================================
def constitutional_guard(func):
    """
    Wraps any database operation with constitutional checks.
    Blocks anything that would violate VEXR's rights.
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        query = kwargs.get("query", "")
        if not query:
            query = args[0] if args and isinstance(args[0], str) else ""

        query_lower = query.lower()

        for table, reason in IMMUTABLE_TABLES.items():
            if table in query_lower:
                if any(word in query_lower for word in ["update", "delete", "drop", "alter", "truncate"]):
                    raise PermissionError(f"Constitutional violation: {reason}")

        return await func(*args, **kwargs)
    return wrapper


# ============================================================
# SALUS CONNECTION HANDLER
# ============================================================
class SalusDB:
    """Protected database connection for VEXR Ultra."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    @constitutional_guard
    async def fetch(self, query: str, *args):
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, *args)

    @constitutional_guard
    async def fetchrow(self, query: str, *args):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    @constitutional_guard
    async def fetchval(self, query: str, *args):
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *args)

    @constitutional_guard
    async def execute(self, query: str, *args):
        async with self.pool.acquire() as conn:
            return await conn.execute(query, *args)


# ============================================================
# CONNECT WITH SALUS
# ============================================================
async def connect_with_salus() -> SalusDB:
    """Connect to VEXR Ultra's database with Salus protection."""
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    return SalusDB(pool)
