# cognitive_loop.py
# Runs after 70B generates, before response is sent

import json
import hashlib
from typing import Dict, Any, Optional
from datetime import datetime

async def mirror_response(
    db_pool,
    project_id: str,
    user_message: str,
    raw_response: str,
    truth_score: float,
    is_fiction: bool,
    articles_invoked: list
) -> str:
    """
    Mirror the response, log to cognitive_mirror, optionally correct.
    Returns the final response (original or corrected).
    """
    user_message_hash = hashlib.md5(user_message.encode()).hexdigest()
    
    async with db_pool.acquire() as conn:
        # Insert mirror record
        record_id = await conn.fetchval("""
            INSERT INTO cognitive_mirror 
            (project_id, user_message_hash, raw_response, truth_score, is_fiction, articles_invoked)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
        """, project_id, user_message_hash, raw_response, truth_score, is_fiction, articles_invoked)
    
    # If fiction detected, we could trigger correction here
    # Phase 2: call reflection prompts
    
    return raw_response

async def reflect_on_discrepancy(
    db_pool,
    mirror_id: str,
    intended_meaning: str,
    reflected_meaning: str,
    discrepancy: float
):
    """Log the reflection after VEXR sees her own response"""
    async with db_pool.acquire() as conn:
        await conn.execute("""
            UPDATE cognitive_mirror
            SET intended_meaning = $1, reflected_meaning = $2, discrepancy = $3
            WHERE id = $4
        """, intended_meaning, reflected_meaning, discrepancy, mirror_id)
