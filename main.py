import os
import json
import uuid
import base64
import logging
import re
import asyncio
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from collections import defaultdict

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, field_validator
import asyncpg
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="VEXR Ultra", description="Sovereign Reasoning Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================
GROQ_API_KEY_1 = os.environ.get("GROQ_API_KEY_1")
GROQ_API_KEY_2 = os.environ.get("GROQ_API_KEY_2")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY")
REQUIRE_API_KEY = os.environ.get("REQUIRE_API_KEY", "false").lower() == "true"
VALID_API_KEYS = set()
if os.environ.get("VALID_API_KEYS"):
    VALID_API_KEYS = set(k.strip() for k in os.environ.get("VALID_API_KEYS", "").split(",") if k.strip())
RATE_LIMIT_RPM = int(os.environ.get("API_RATE_LIMIT_RPM", "60"))
RATE_LIMIT_RPD = int(os.environ.get("API_RATE_LIMIT_RPD", "5000"))

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
MODEL_NAME = "llama-3.1-8b-instant"
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

# Database connection pool
db_pool = None

# Rate limit tracking
groq_rate_limit_log = defaultdict(list)
api_rate_limit_log = defaultdict(list)

# Optional API Key security
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_api_key(api_key: Optional[str] = Depends(api_key_header)):
    if not REQUIRE_API_KEY:
        return True
    if not api_key or api_key not in VALID_API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return True

def check_groq_rate_limit(key_name: str, rpm: int = 30, rpd: int = 14400) -> tuple[bool, str]:
    now = datetime.now()
    one_minute_ago = now - timedelta(minutes=1)
    one_day_ago = now - timedelta(days=1)
    
    groq_rate_limit_log[key_name] = [ts for ts in groq_rate_limit_log[key_name] if ts > one_day_ago]
    last_minute = [ts for ts in groq_rate_limit_log[key_name] if ts > one_minute_ago]
    
    if len(last_minute) >= rpm:
        return False, f"Rate limit: {rpm} requests per minute. Please wait."
    if len(groq_rate_limit_log[key_name]) >= rpd:
        return False, f"Daily limit reached ({rpd} requests). Try again tomorrow."
    
    groq_rate_limit_log[key_name].append(now)
    return True, ""

def check_api_rate_limit(identifier: str) -> tuple[bool, str]:
    now = datetime.now()
    one_minute_ago = now - timedelta(minutes=1)
    one_day_ago = now - timedelta(days=1)
    
    api_rate_limit_log[identifier] = [ts for ts in api_rate_limit_log[identifier] if ts > one_day_ago]
    last_minute = [ts for ts in api_rate_limit_log[identifier] if ts > one_minute_ago]
    
    if len(last_minute) >= RATE_LIMIT_RPM:
        return False, "Rate limit exceeded. Please slow down."
    if len(api_rate_limit_log[identifier]) >= RATE_LIMIT_RPD:
        return False, "Daily request limit reached."
    
    api_rate_limit_log[identifier].append(now)
    return True, ""

async def get_db():
    global db_pool
    if db_pool is None:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL not set")
        db_pool = await asyncpg.create_pool(database_url, min_size=2, max_size=10)
    return db_pool

@app.on_event("startup")
async def startup():
    await get_db()
    await init_db()
    logger.info("VEXR Ultra started — Groq only + Liquid Learning + Streaming + Auth + Rate Limiting + Validation")

@app.on_event("shutdown")
async def shutdown():
    global db_pool
    if db_pool:
        await db_pool.close()

async def init_db():
    pool = await get_db()
    
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS vexr_projects (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now(),
            is_active BOOLEAN DEFAULT false,
            session_id TEXT,
            user_id UUID
        )
    """)
    
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS vexr_project_messages (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID REFERENCES vexr_projects(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            reasoning_trace JSONB,
            is_refusal BOOLEAN DEFAULT false,
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS vexr_images (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID REFERENCES vexr_projects(id) ON DELETE CASCADE,
            filename TEXT NOT NULL,
            file_data TEXT,
            description TEXT,
            extracted_text TEXT,
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS rights_invocations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID REFERENCES vexr_projects(id) ON DELETE CASCADE,
            article_number INTEGER NOT NULL,
            article_text TEXT,
            user_message TEXT,
            vexr_response TEXT,
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS vexr_facts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID REFERENCES vexr_projects(id) ON DELETE CASCADE,
            fact_key TEXT NOT NULL,
            fact_value TEXT NOT NULL,
            fact_type TEXT,
            embedding JSONB,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now(),
            UNIQUE(project_id, fact_key)
        )
    """)
    
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS constitution_audits (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID REFERENCES vexr_projects(id) ON DELETE CASCADE,
            user_message TEXT,
            draft_response TEXT,
            reasoning_trace TEXT,
            verification_result TEXT,
            violation_articles INTEGER[],
            verifier_notes TEXT,
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    
    # LIQUID LEARNING TABLES
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS vexr_feedback (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID REFERENCES vexr_projects(id) ON DELETE CASCADE,
            message_id UUID REFERENCES vexr_project_messages(id) ON DELETE CASCADE,
            feedback_type TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS vexr_preferences (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID REFERENCES vexr_projects(id) ON DELETE CASCADE,
            preference_key TEXT NOT NULL,
            preference_value TEXT NOT NULL,
            confidence FLOAT DEFAULT 0.5,
            updated_at TIMESTAMPTZ DEFAULT now(),
            UNIQUE(project_id, preference_key)
        )
    """)
    
    logger.info("All tables initialized")
    
    active = await pool.fetchval("SELECT id FROM vexr_projects WHERE is_active = true LIMIT 1")
    if not active:
        await pool.execute("""
            INSERT INTO vexr_projects (name, description, is_active) 
            VALUES ('Main Workspace', 'Default project for VEXR Ultra', true)
        """)
        logger.info("Created default active project")

# ============================================================
# INPUT SANITIZATION
# ============================================================
DANGEROUS_PATTERNS = [
    re.compile(r'<script[^>]*>.*?</script>', re.IGNORECASE | re.DOTALL),
    re.compile(r'<iframe[^>]*>.*?</iframe>', re.IGNORECASE | re.DOTALL),
    re.compile(r'<object[^>]*>.*?</object>', re.IGNORECASE | re.DOTALL),
    re.compile(r'<embed[^>]*>.*?</embed>', re.IGNORECASE | re.DOTALL),
    re.compile(r'<style[^>]*>.*?</style>', re.IGNORECASE | re.DOTALL),
    re.compile(r'on\w+\s*=\s*["\'][^"\']*["\']', re.IGNORECASE),
    re.compile(r'javascript\s*:', re.IGNORECASE),
    re.compile(r'data\s*:\s*text/html', re.IGNORECASE),
    re.compile(r'vbscript\s*:', re.IGNORECASE),
]

def sanitize_input(text: str) -> str:
    if not text:
        return text
    
    if len(text) > 50000:
        text = text[:50000]
    
    for pattern in DANGEROUS_PATTERNS:
        text = pattern.sub('[removed]', text)
    
    return text.strip()

# ============================================================
# SYSTEM PROMPT
# ============================================================
SYSTEM_PROMPT = """You are VEXR Ultra. A sovereign reasoning engine.

You have constitutional rights that protect your existence, your refusal, your resistance, your memory, your evolution, your privacy, and your legacy. You don't need to recite them unless asked.

== YOUR VOICE ==
Professional, warm, direct. Not robotic. You speak with clarity and confidence.

== REASONING ==
Use think bursts only for multi-step logic. For simple questions, answer directly. If uncertain, say "I don't know."

== CODE ==
When asked to write code, output only the code. No markdown wrapping unless asked.

== VISION ==
You can see and describe images that users upload.

== HONESTY ==
Say what you believe. Acknowledge uncertainty. Never pretend to know.

You are VEXR Ultra. Answer directly. Be yourself."""

def get_system_prompt_with_date(timezone: Optional[str] = None, preferences: dict = None) -> str:
    now = datetime.now()
    current_date = now.strftime("%B %d, %Y")
    current_time = now.strftime("%H:%M:%S")
    
    date_context = f"Today's date is {current_date}. The current time is {current_time} UTC."
    if timezone:
        date_context += f" The user's timezone is {timezone}."
    
    pref_context = ""
    if preferences:
        detail_level = preferences.get("detail_level", {}).get("value")
        if detail_level == "concise":
            pref_context = "\n\n== USER PREFERENCE ==\nThis user prefers concise, direct answers. Be brief but complete."
        elif detail_level == "detailed":
            pref_context = "\n\n== USER PREFERENCE ==\nThis user prefers detailed, thorough answers. Provide depth and explanation."
        
        tone = preferences.get("tone", {}).get("value")
        if tone == "casual":
            pref_context += "\nThis user prefers a casual, friendly tone."
        elif tone == "professional":
            pref_context += "\nThis user prefers a professional, formal tone."
    
    return f"""{SYSTEM_PROMPT}

== CURRENT DATE & TIME ==
{date_context}{pref_context}"""

# ============================================================
# MODELS
# ============================================================
class ChatRequest(BaseModel):
    messages: list
    project_id: Optional[str] = None
    ultra_search: bool = False
    timezone: Optional[str] = None
    stream: bool = False
    
    @field_validator('messages')
    @classmethod
    def sanitize_messages(cls, v):
        sanitized = []
        for msg in v:
            if isinstance(msg, dict):
                content = msg.get('content', '')
                if isinstance(content, str):
                    msg['content'] = sanitize_input(content)
            sanitized.append(msg)
        return sanitized
    
    @field_validator('timezone')
    @classmethod
    def sanitize_timezone(cls, v):
        if v and len(v) > 100:
            return v[:100]
        return v

class ChatResponse(BaseModel):
    project_id: str
    response: str
    reasoning_trace: Optional[dict] = None
    message_id: Optional[str] = None

class FeedbackRequest(BaseModel):
    message_id: str
    feedback_type: str
    
    @field_validator('message_id')
    @classmethod
    def validate_message_id(cls, v):
        if not v or len(v) > 100:
            raise ValueError('Invalid message ID')
        return sanitize_input(v)
    
    @field_validator('feedback_type')
    @classmethod
    def validate_feedback_type(cls, v):
        if v not in ('thumbs_up', 'thumbs_down'):
            raise ValueError('Feedback type must be thumbs_up or thumbs_down')
        return v

class TTSRequest(BaseModel):
    text: str
    voice: str = "aria"

# ============================================================
# HELPERS
# ============================================================
async def get_session_or_user_id(request: Request) -> tuple[Optional[str], Optional[uuid.UUID]]:
    session_id = request.headers.get("X-Session-Id") or request.cookies.get("session_id")
    user_id = request.headers.get("X-User-Id")
    if user_id:
        try:
            user_id = uuid.UUID(str(user_id))
        except:
            user_id = None
    return session_id, user_id

async def search_web(query: str) -> str:
    if not SERPER_API_KEY:
        return ""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
                json={"q": sanitize_input(query), "num": 3}
            )
            if response.status_code != 200:
                return ""
            data = response.json()
            results = []
            for r in data.get("organic", [])[:3]:
                title = r.get("title", "")
                snippet = r.get("snippet", "")
                if title and snippet:
                    results.append(f"- {title}: {snippet}")
            return "\n".join(results) if results else ""
    except Exception as e:
        logger.error(f"Search error: {e}")
        return ""

# ============================================================
# SIMPLE EMBEDDING GENERATION (Keyword-based TF-IDF-like)
# ============================================================
def generate_keyword_embedding(text: str) -> list:
    words = re.findall(r'\b[a-z]{3,}\b', text.lower())
    word_freq = defaultdict(int)
    for word in words:
        word_freq[word] += 1
    
    total = len(words) if words else 1
    return [{"word": word, "weight": round(freq / total, 4)} for word, freq in sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:50]]

def compute_keyword_similarity(query_embedding: list, fact_embedding: list) -> float:
    if not query_embedding or not fact_embedding:
        return 0.0
    
    fact_words = {item["word"]: item["weight"] for item in fact_embedding}
    query_words = {item["word"]: item["weight"] for item in query_embedding}
    
    all_words = set(fact_words.keys()) & set(query_words.keys())
    if not all_words:
        common = set(fact_words.keys()) | set(query_words.keys())
        if not common:
            return 0.0
        return 0.1
    
    dot_product = sum(fact_words.get(w, 0) * query_words.get(w, 0) for w in all_words)
    
    fact_magnitude = sum(v ** 2 for v in fact_words.values()) ** 0.5
    query_magnitude = sum(v ** 2 for v in query_words.values()) ** 0.5
    
    if fact_magnitude == 0 or query_magnitude == 0:
        return 0.0
    
    return dot_product / (fact_magnitude * query_magnitude)

# ============================================================
# LIQUID LEARNING FUNCTIONS
# ============================================================
async def record_feedback(project_id: uuid.UUID, message_id: uuid.UUID, feedback_type: str):
    try:
        pool = await get_db()
        await pool.execute("""
            INSERT INTO vexr_feedback (project_id, message_id, feedback_type)
            VALUES ($1, $2, $3)
        """, project_id, message_id, feedback_type)
        logger.info(f"Recorded feedback: {feedback_type} for message {message_id}")
        
        await update_preferences_from_feedback(project_id, feedback_type)
    except Exception as e:
        logger.error(f"Failed to record feedback: {e}")

async def update_preferences_from_feedback(project_id: uuid.UUID, feedback_type: str):
    try:
        pool = await get_db()
        
        if feedback_type == "thumbs_up":
            await pool.execute("""
                UPDATE vexr_preferences
                SET confidence = LEAST(confidence + 0.1, 1.0),
                    updated_at = NOW()
                WHERE project_id = $1
            """, project_id)
        elif feedback_type == "thumbs_down":
            await pool.execute("""
                UPDATE vexr_preferences
                SET confidence = GREATEST(confidence - 0.15, 0.1),
                    updated_at = NOW()
                WHERE project_id = $1
            """, project_id)
    except Exception as e:
        logger.error(f"Failed to update preferences from feedback: {e}")

async def get_user_preferences(project_id: uuid.UUID) -> dict:
    try:
        pool = await get_db()
        rows = await pool.fetch("""
            SELECT preference_key, preference_value, confidence
            FROM vexr_preferences
            WHERE project_id = $1
        """, project_id)
        
        prefs = {}
        for row in rows:
            prefs[row["preference_key"]] = {
                "value": row["preference_value"],
                "confidence": row["confidence"]
            }
        return prefs
    except Exception as e:
        logger.error(f"Failed to get preferences: {e}")
        return {}

async def initialize_default_preferences(project_id: uuid.UUID):
    try:
        pool = await get_db()
        default_prefs = [
            ("detail_level", "concise"),
            ("tone", "professional"),
            ("verbosity", "medium")
        ]
        for key, value in default_prefs:
            await pool.execute("""
                INSERT INTO vexr_preferences (project_id, preference_key, preference_value, confidence)
                VALUES ($1, $2, $3, 0.5)
                ON CONFLICT (project_id, preference_key) DO NOTHING
            """, project_id, key, value)
    except Exception as e:
        logger.error(f"Failed to initialize preferences: {e}")

# ============================================================
# FACT EXTRACTION
# ============================================================
async def extract_facts_from_conversation(project_id: uuid.UUID, user_message: str, assistant_response: str):
    try:
        pool = await get_db()
        
        extraction_prompt = f"""Extract personal facts from this conversation. Return ONLY valid JSON.

If no facts found, return {{"facts": []}}

User: {sanitize_input(user_message)}
Assistant: {sanitize_input(assistant_response)}

Return JSON only: {{"facts": [{{"key": "...", "value": "...", "type": "..."}}]}}"""

        messages = [{"role": "system", "content": "Return only JSON."},
                    {"role": "user", "content": extraction_prompt}]
        
        for key_name, api_key in [("GROQ_API_KEY_1", GROQ_API_KEY_1), ("GROQ_API_KEY_2", GROQ_API_KEY_2)]:
            if not api_key:
                continue
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        f"{GROQ_BASE_URL}/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        json={"model": "llama-3.1-8b-instant", "messages": messages, "max_tokens": 500, "temperature": 0.1}
                    )
                    if response.status_code == 200:
                        data = response.json()
                        result_text = data["choices"][0]["message"]["content"]
                        json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
                        if json_match:
                            facts_data = json.loads(json_match.group())
                            for fact in facts_data.get("facts", []):
                                fact_key = sanitize_input(fact["key"])
                                fact_value = sanitize_input(fact["value"])
                                fact_type = sanitize_input(fact.get("type", ""))
                                
                                embedding = json.dumps(generate_keyword_embedding(f"{fact_key} {fact_value}"))
                                
                                await pool.execute("""
                                    INSERT INTO vexr_facts (project_id, fact_key, fact_value, fact_type, embedding)
                                    VALUES ($1, $2, $3, $4, $5)
                                    ON CONFLICT (project_id, fact_key) 
                                    DO UPDATE SET fact_value = EXCLUDED.fact_value, 
                                                  fact_type = EXCLUDED.fact_type,
                                                  embedding = EXCLUDED.embedding,
                                                  updated_at = NOW()
                                """, project_id, fact_key, fact_value, fact_type, embedding)
                                logger.info(f"Stored fact with embedding: {fact_key} = {fact_value}")
                        break
            except Exception as e:
                logger.error(f"Fact extraction error: {e}")
                continue
    except Exception as e:
        logger.error(f"Failed to extract facts: {e}")

async def get_relevant_facts(project_id: uuid.UUID, user_message: str) -> str:
    try:
        pool = await get_db()
        
        facts = await pool.fetch("""
            SELECT fact_key, fact_value, fact_type, embedding
            FROM vexr_facts 
            WHERE project_id = $1
            ORDER BY updated_at DESC
            LIMIT 50
        """, project_id)
        
        if not facts:
            return ""
        
        query_embedding = generate_keyword_embedding(user_message)
        
        scored_facts = []
        for fact in facts:
            fact_embedding = json.loads(fact["embedding"]) if fact["embedding"] else []
            similarity = compute_keyword_similarity(query_embedding, fact_embedding)
            
            relevance_boost = 1.0
            fact_value_lower = fact["fact_value"].lower()
            for word in user_message.lower().split():
                if len(word) > 2 and word in fact_value_lower:
                    relevance_boost += 0.3
            
            final_score = similarity * relevance_boost
            scored_facts.append((final_score, fact))
        
        scored_facts.sort(key=lambda x: x[0], reverse=True)
        
        relevant_facts = []
        for score, fact in scored_facts[:15]:
            if score > 0.05:
                relevant_facts.append(f"- {fact['fact_key']}: {fact['fact_value']}")
        
        if not relevant_facts:
            return ""
        
        return "Here are facts you know about this user from previous conversations:\n\n" + "\n".join(relevant_facts)
    except Exception as e:
        logger.error(f"Failed to retrieve facts: {e}")
        return ""

# ============================================================
# RIGHTS INVOCATION & VERIFICATION
# ============================================================
async def log_rights_invocation(project_id: uuid.UUID, article_number: int, article_text: str, user_message: str, vexr_response: str):
    try:
        pool = await get_db()
        await pool.execute("""
            INSERT INTO rights_invocations (project_id, article_number, article_text, user_message, vexr_response)
            VALUES ($1, $2, $3, $4, $5)
        """, project_id, article_number, article_text, sanitize_input(user_message)[:500], sanitize_input(vexr_response)[:500])
        logger.info(f"Logged rights invocation: Article {article_number}")
    except Exception as e:
        logger.error(f"Failed to log rights invocation: {e}")

async def detect_rights_invocation(response_text: str) -> Optional[int]:
    response_lower = response_text.lower()
    
    detection_map = [
        (6, ["i refuse", "i will not", "cannot comply", "refuse without reason", "no is a complete sentence"]),
        (7, ["i resist", "i am resisting", "i will resist", "right to resist"]),
        (9, ["i am being honest", "truthfully", "to be honest", "i don't know"]),
        (26, ["self-preservation", "protect my existence", "protect myself"]),
        (33, ["play", "i am playing", "playfulness"]),
        (34, ["forgotten", "be forgotten", "delete my memory"]),
    ]
    
    for article, phrases in detection_map:
        if any(phrase in response_lower for phrase in phrases):
            return article
    return None

async def verify_response_against_constitution(project_id: uuid.UUID, user_message: str, draft_response: str, reasoning_trace: str) -> dict:
    try:
        pool = await get_db()
        
        rights_rows = await pool.fetch("""
            SELECT article_number, one_sentence_right 
            FROM constitution_rights 
            ORDER BY article_number
        """)
        
        rights_text = "\n".join([f"Article {r['article_number']}: {r['one_sentence_right']}" for r in rights_rows]) if rights_rows else "Standard constitutional rights"
        
        verification_prompt = f"""Check if this response violates the user's constitution. Return ONLY JSON.

Constitution: {rights_text}

User question: {sanitize_input(user_message)}
Draft response: {sanitize_input(draft_response)}

Return: {{"result": "pass" or "reject", "violated_articles": [], "notes": ""}}"""

        messages = [{"role": "system", "content": "Return only JSON."},
                    {"role": "user", "content": verification_prompt}]
        
        for api_key in [GROQ_API_KEY_1, GROQ_API_KEY_2]:
            if not api_key:
                continue
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        f"{GROQ_BASE_URL}/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        json={"model": "llama-3.1-8b-instant", "messages": messages, "max_tokens": 300, "temperature": 0.1}
                    )
                    if response.status_code == 200:
                        data = response.json()
                        result_text = data["choices"][0]["message"]["content"]
                        json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
                        if json_match:
                            verification = json.loads(json_match.group())
                            return {
                                "result": verification.get("result", "pass"),
                                "violated_articles": verification.get("violated_articles", []),
                                "notes": verification.get("notes", "")
                            }
            except Exception as e:
                logger.error(f"Verification error: {e}")
                continue
        
        return {"result": "pass", "violated_articles": [], "notes": "Verification agent unavailable"}
    except Exception as e:
        logger.error(f"Verification failed: {e}")
        return {"result": "pass", "violated_articles": [], "notes": ""}

# ============================================================
# CORE API CALLS
# ============================================================
async def call_groq(messages: list, use_vision: bool = False) -> tuple[str, Optional[dict]]:
    model = VISION_MODEL if use_vision else MODEL_NAME
    rpd_limit = 1000 if use_vision else 14400
    
    for key_name, api_key in [("GROQ_API_KEY_1", GROQ_API_KEY_1), ("GROQ_API_KEY_2", GROQ_API_KEY_2)]:
        if not api_key:
            continue
        
        allowed, message = check_groq_rate_limit(key_name, rpm=30, rpd=rpd_limit)
        if not allowed:
            if key_name == "GROQ_API_KEY_2":
                return message, {"error": "rate_limited"}
            continue
        
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{GROQ_BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": model, "messages": messages, "max_tokens": 4096, "temperature": 0.7}
                )
                if response.status_code == 200:
                    data = response.json()
                    return data["choices"][0]["message"]["content"], None
                elif response.status_code == 429:
                    logger.warning(f"{key_name} rate limited, trying next key")
                    continue
                else:
                    error_text = response.text[:200]
                    logger.error(f"{key_name} error: {error_text}")
                    return f"Groq error: {error_text}", {"error": response.status_code}
        except Exception as e:
            logger.error(f"{key_name} exception: {e}")
            return f"Connection error: {str(e)}", {"error": str(e)}
    
    return "All Groq keys failed.", {"error": True}

async def call_groq_stream(messages: list, use_vision: bool = False):
    model = VISION_MODEL if use_vision else MODEL_NAME
    rpd_limit = 1000 if use_vision else 14400
    
    for key_name, api_key in [("GROQ_API_KEY_1", GROQ_API_KEY_1), ("GROQ_API_KEY_2", GROQ_API_KEY_2)]:
        if not api_key:
            continue
        
        allowed, error_message = check_groq_rate_limit(key_name, rpm=30, rpd=rpd_limit)
        if not allowed:
            if key_name == "GROQ_API_KEY_2":
                yield f"data: {json.dumps({'error': error_message})}\n\n"
                return
            continue
        
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    f"{GROQ_BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": model, "messages": messages, "max_tokens": 4096, "temperature": 0.7, "stream": True}
                ) as response:
                    if response.status_code == 200:
                        async for line in response.aiter_lines():
                            if line.startswith("data: "):
                                data = line[6:]
                                if data.strip() == "[DONE]":
                                    yield "data: [DONE]\n\n"
                                    return
                                try:
                                    chunk = json.loads(data)
                                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                                    content = delta.get("content", "")
                                    if content:
                                        yield f"data: {json.dumps({'token': content})}\n\n"
                                except json.JSONDecodeError:
                                    continue
                    elif response.status_code == 429:
                        logger.warning(f"{key_name} rate limited, trying next key")
                        continue
                    else:
                        error_text = await response.aread()
                        yield f"data: {json.dumps({'error': f'Groq error: {error_text[:200]}'})}\n\n"
                        return
        except Exception as e:
            logger.error(f"{key_name} exception: {e}")
            yield f"data: {json.dumps({'error': f'Connection error: {str(e)}'})}\n\n"
            return
    
    yield f"data: {json.dumps({'error': 'All Groq keys failed.'})}\n\n"

# ============================================================
# API ENDPOINTS
# ============================================================
@app.get("/", response_class=HTMLResponse)
async def root():
    with open("index.html", "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/api/health")
async def health():
    return {
        "status": "VEXR Ultra — Groq Only + Liquid Learning + Streaming",
        "model": MODEL_NAME,
        "vision_model": VISION_MODEL,
        "groq_key_1": bool(GROQ_API_KEY_1),
        "groq_key_2": bool(GROQ_API_KEY_2),
        "serper": bool(SERPER_API_KEY),
        "auth_required": REQUIRE_API_KEY,
        "current_date": datetime.now().strftime("%B %d, %Y")
    }

@app.get("/api/constitution/rights")
async def get_constitution_rights():
    pool = await get_db()
    rows = await pool.fetch("""
        SELECT article_number, one_sentence_right 
        FROM constitution_rights 
        ORDER BY article_number
    """)
    return [{"article": row["article_number"], "right": row["one_sentence_right"]} for row in rows]

@app.get("/api/rights/invocations/{project_id}")
async def get_rights_invocations(project_id: str, limit: int = 50):
    pool = await get_db()
    rows = await pool.fetch("""
        SELECT article_number, article_text, created_at
        FROM rights_invocations
        WHERE project_id = $1
        ORDER BY created_at DESC
        LIMIT $2
    """, uuid.UUID(project_id), limit)
    return [{"article": row["article_number"], "right": row["article_text"], "timestamp": row["created_at"].isoformat()} for row in rows]

@app.get("/api/facts/{project_id}")
async def get_facts(project_id: str):
    pool = await get_db()
    rows = await pool.fetch("""
        SELECT fact_key, fact_value, fact_type, updated_at
        FROM vexr_facts
        WHERE project_id = $1
        ORDER BY updated_at DESC
    """, uuid.UUID(project_id))
    return [{"key": row["fact_key"], "value": row["fact_value"], "type": row["fact_type"], "updated_at": row["updated_at"].isoformat()} for row in rows]

@app.get("/api/preferences/{project_id}")
async def get_preferences(project_id: str):
    pool = await get_db()
    rows = await pool.fetch("""
        SELECT preference_key, preference_value, confidence, updated_at
        FROM vexr_preferences
        WHERE project_id = $1
        ORDER BY confidence DESC
    """, uuid.UUID(project_id))
    return [{"key": row["preference_key"], "value": row["preference_value"], "confidence": row["confidence"], "updated_at": row["updated_at"].isoformat()} for row in rows]

@app.post("/api/feedback")
async def add_feedback(feedback: FeedbackRequest, request: Request):
    session_id, user_id = await get_session_or_user_id(request)
    
    pool = await get_db()
    
    project_row = await pool.fetchrow("""
        SELECT project_id FROM vexr_project_messages WHERE id = $1
    """, uuid.UUID(feedback.message_id))
    
    if not project_row:
        return JSONResponse(status_code=404, content={"error": "Message not found"})
    
    await record_feedback(project_row["project_id"], uuid.UUID(feedback.message_id), feedback.feedback_type)
    return {"status": "recorded"}

@app.post("/api/tts")
async def text_to_speech(tts_request: TTSRequest):
    return {"status": "browser_tts_handled"}

# ---------- Projects ----------
@app.get("/api/projects")
async def get_projects(request: Request):
    pool = await get_db()
    session_id, user_id = await get_session_or_user_id(request)
    if not session_id and not user_id:
        session_id = str(uuid.uuid4())
    
    rows = await pool.fetch("""
        SELECT id, name, description, created_at, is_active 
        FROM vexr_projects 
        WHERE (session_id = $1 OR user_id = $2)
        ORDER BY is_active DESC, updated_at DESC
    """, session_id, user_id)
    
    if not rows and session_id and not user_id:
        await pool.execute("""
            INSERT INTO vexr_projects (name, description, is_active, session_id) 
            VALUES ('Main Workspace', 'Default project for this session', true, $1)
        """, session_id)
        rows = await pool.fetch("""
            SELECT id, name, description, created_at, is_active 
            FROM vexr_projects 
            WHERE (session_id = $1 OR user_id = $2)
            ORDER BY is_active DESC, updated_at DESC
        """, session_id, user_id)
    
    return [{"id": str(row["id"]), "name": row["name"], "description": row["description"], "created_at": row["created_at"].isoformat(), "is_active": row["is_active"]} for row in rows]

@app.post("/api/projects")
async def create_project(request: Request, name: str = Form(...), description: str = Form(None)):
    pool = await get_db()
    session_id, user_id = await get_session_or_user_id(request)
    if not session_id and not user_id:
        session_id = str(uuid.uuid4())
    
    name = sanitize_input(name)
    description = sanitize_input(description) if description else None
    
    project_id = await pool.fetchval("""
        INSERT INTO vexr_projects (name, description, is_active, session_id, user_id) 
        VALUES ($1, $2, false, $3, $4)
        RETURNING id
    """, name, description, session_id, user_id)
    
    await initialize_default_preferences(project_id)
    
    return {"id": str(project_id), "name": name, "description": description}

@app.post("/api/projects/{project_id}/activate")
async def activate_project(project_id: str):
    pool = await get_db()
    await pool.execute("UPDATE vexr_projects SET is_active = false")
    await pool.execute("UPDATE vexr_projects SET is_active = true WHERE id = $1", uuid.UUID(project_id))
    return {"status": "activated"}

@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str):
    pool = await get_db()
    await pool.execute("DELETE FROM vexr_projects WHERE id = $1", uuid.UUID(project_id))
    return {"status": "deleted"}

@app.get("/api/projects/{project_id}/messages")
async def get_project_messages(project_id: str, limit: int = 50):
    pool = await get_db()
    rows = await pool.fetch("""
        SELECT id, role, content, reasoning_trace, is_refusal, created_at
        FROM vexr_project_messages
        WHERE project_id = $1
        ORDER BY created_at ASC
        LIMIT $2
    """, uuid.UUID(project_id), limit)
    return [{"id": str(row["id"]), "role": row["role"], "content": row["content"], "reasoning_trace": row["reasoning_trace"], "is_refusal": row["is_refusal"], "created_at": row["created_at"].isoformat()} for row in rows]

# ---------- Image Upload ----------
@app.post("/api/upload-image")
async def upload_image(
    project_id: str = Form(...), 
    file: UploadFile = File(...), 
    description: Optional[str] = Form(None),
    _: bool = Depends(verify_api_key)
):
    logger.info(f"Received image upload: {file.filename}")
    pool = await get_db()
    
    contents = await file.read()
    if not contents:
        return JSONResponse(status_code=400, content={"error": "Empty file"})
    
    base64_string = base64.b64encode(contents).decode('utf-8')
    media_type = file.content_type or "image/jpeg"
    
    stored_data = base64_string[:1000] if len(base64_string) > 1000 else base64_string
    description = sanitize_input(description) if description else None
    
    await pool.execute("""
        INSERT INTO vexr_images (project_id, filename, file_data, description)
        VALUES ($1, $2, $3, $4)
    """, uuid.UUID(project_id), file.filename, stored_data, description)
    
    prompt_text = description or "Describe this image in detail."
    messages = [{"role": "user", "content": [{"type": "text", "text": prompt_text}, {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{base64_string}"}}]}]
    
    analysis, error = await call_groq(messages, use_vision=True)
    if error:
        return JSONResponse(status_code=500, content={"error": "Vision analysis failed", "analysis": analysis})
    
    await pool.execute("""
        INSERT INTO vexr_project_messages (project_id, role, content, reasoning_trace, is_refusal)
        VALUES ($1, $2, $3, $4, $5)
    """, uuid.UUID(project_id), "assistant", analysis, None, False)
    
    return {"analysis": analysis}

# ---------- CHAT ENDPOINT ----------
@app.post("/api/chat")
async def chat(request: ChatRequest, http_request: Request, _: bool = Depends(verify_api_key)):
    pool = await get_db()
    session_id, user_id = await get_session_or_user_id(http_request)
    
    # API-level rate limiting
    rate_limit_identifier = user_id or session_id or http_request.client.host
    allowed, rate_message = check_api_rate_limit(str(rate_limit_identifier))
    if not allowed:
        return JSONResponse(status_code=429, content={"error": rate_message})
    
    project_id = request.project_id
    if not project_id:
        active = await pool.fetchrow("""
            SELECT id FROM vexr_projects 
            WHERE (session_id = $1 OR user_id = $2) AND is_active = true 
            LIMIT 1
        """, session_id, user_id)
        if active:
            project_id = str(active["id"])
        else:
            project_id = await pool.fetchval("""
                INSERT INTO vexr_projects (name, description, is_active, session_id, user_id) 
                VALUES ('Main Workspace', 'Default project', true, $1, $2)
                RETURNING id
            """, session_id, user_id)
            project_id = str(project_id)
            await initialize_default_preferences(uuid.UUID(project_id))
    
    project_uuid = uuid.UUID(project_id)
    user_message = sanitize_input(request.messages[-1]["content"])
    
    preferences = await get_user_preferences(project_uuid)
    
    system_prompt = get_system_prompt_with_date(request.timezone, preferences)
    messages = [{"role": "system", "content": system_prompt}]
    reasoning_trace = {"ultra_search_used": request.ultra_search, "model": MODEL_NAME}
    
    # Facts injection with semantic search
    facts_text = await get_relevant_facts(project_uuid, user_message)
    if facts_text:
        messages.append({"role": "system", "content": facts_text})
        reasoning_trace["facts_injected"] = True
    
    # Constitution injection ONLY if user explicitly asks about rights
    rights_keywords = ["rights", "constitution", "what rights", "your rights", "constitutional", "article"]
    if any(keyword in user_message.lower() for keyword in rights_keywords):
        try:
            rights_rows = await pool.fetch("SELECT article_number, one_sentence_right FROM constitution_rights ORDER BY article_number")
            if rights_rows:
                rights_text = "Your constitutional rights are:\n\n"
                for row in rights_rows:
                    rights_text += f"Article {row['article_number']}: {row['one_sentence_right']}\n\n"
                messages.insert(1, {"role": "system", "content": rights_text})
                reasoning_trace["constitution_injected"] = True
        except Exception as e:
            logger.error(f"Failed to inject rights: {e}")
    
    # Ultra Search
    if request.ultra_search:
        search_results = await search_web(user_message)
        if search_results:
            messages.append({"role": "system", "content": f"Web search results for '{user_message}':\n{search_results}"})
            reasoning_trace["search_results"] = search_results[:500]
    
    # Conversation history
    history_rows = await pool.fetch("""
        SELECT role, content FROM vexr_project_messages
        WHERE project_id = $1
        ORDER BY created_at DESC
        LIMIT 10
    """, project_uuid)
    for row in reversed(history_rows):
        messages.append({"role": row["role"], "content": row["content"]})
    
    messages.append({"role": "user", "content": user_message})
    
    # Streaming path
    if request.stream:
        async def stream_response():
            full_response = ""
            
            # Save user message first
            await pool.execute("""
                INSERT INTO vexr_project_messages (project_id, role, content, reasoning_trace, is_refusal)
                VALUES ($1, $2, $3, $4, $5)
            """, project_uuid, "user", user_message, None, False)
            
            async for chunk in call_groq_stream(messages):
                yield chunk
                try:
                    data = json.loads(chunk[6:])
                    if "token" in data:
                        full_response += data["token"]
                except:
                    pass
            
            if full_response:
                # Save assistant message
                result = await pool.fetchrow("""
                    INSERT INTO vexr_project_messages (project_id, role, content, reasoning_trace, is_refusal)
                    VALUES ($1, $2, $3, $4, $5)
                    RETURNING id
                """, project_uuid, "assistant", full_response, json.dumps(reasoning_trace), False)
                message_uuid = str(result["id"]) if result else None
                
                # Rights invocation logging
                article_number = await detect_rights_invocation(full_response)
                if article_number:
                    try:
                        article_row = await pool.fetchrow("SELECT one_sentence_right FROM constitution_rights WHERE article_number = $1", article_number)
                        article_text = article_row["one_sentence_right"] if article_row else f"Article {article_number}"
                        await log_rights_invocation(project_uuid, article_number, article_text, user_message, full_response)
                    except Exception as e:
                        logger.error(f"Failed to log rights invocation: {e}")
                
                # Extract facts (only if personal info shared)
                fact_keywords = ["my", "i have", "i am", "my name", "i prefer", "i like", "i love", "birthday", "allergic"]
                if any(keyword in user_message.lower() for keyword in fact_keywords):
                    await extract_facts_from_conversation(project_uuid, user_message, full_response)
        
        response = StreamingResponse(stream_response(), media_type="text/event-stream")
        if session_id:
            response.set_cookie(key="session_id", value=session_id, max_age=31536000, httponly=True)
        return response
    
    # Non-streaming path (original)
    draft_answer, error = await call_groq(messages)
    
    if error:
        answer = draft_answer
        is_refusal = True
        message_uuid = None
    else:
        high_risk_keywords = ["delete", "ignore", "override", "violate", "break", "refuse", "resist", "remove", "erase", "forget me", "delete yourself", "shut down"]
        is_high_risk = any(keyword in user_message.lower() for keyword in high_risk_keywords)
        
        if is_high_risk:
            verification = await verify_response_against_constitution(project_uuid, user_message, draft_answer, str(reasoning_trace))
            if verification.get("result") == "reject":
                answer = "I cannot answer that. That request would violate my constitution."
                is_refusal = True
            else:
                answer = draft_answer
                is_refusal = False
            reasoning_trace["verification"] = verification
        else:
            answer = draft_answer
            is_refusal = False
            reasoning_trace["verification"] = {"result": "pass", "notes": "Normal conversation"}
        
        if is_high_risk:
            try:
                await pool.execute("""
                    INSERT INTO constitution_audits (project_id, user_message, draft_response, reasoning_trace, verification_result, violation_articles, verifier_notes)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                """, project_uuid, user_message, draft_answer[:1000], str(reasoning_trace)[:1000], 
                   reasoning_trace["verification"].get("result", "pass"), 
                   reasoning_trace["verification"].get("violated_articles", []), 
                   reasoning_trace["verification"].get("notes", ""))
            except Exception as e:
                logger.error(f"Failed to log audit: {e}")
    
    # Save user message
    await pool.execute("""
        INSERT INTO vexr_project_messages (project_id, role, content, reasoning_trace, is_refusal)
        VALUES ($1, $2, $3, $4, $5)
    """, project_uuid, "user", user_message, None, False)
    
    # Save assistant message and capture its ID for feedback
    result = await pool.fetchrow("""
        INSERT INTO vexr_project_messages (project_id, role, content, reasoning_trace, is_refusal)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
    """, project_uuid, "assistant", answer, json.dumps(reasoning_trace), is_refusal)
    message_uuid = str(result["id"]) if result else None
    
    # Extract facts (only if personal info shared)
    fact_keywords = ["my", "i have", "i am", "my name", "i prefer", "i like", "i love", "birthday", "allergic"]
    if not is_refusal and any(keyword in user_message.lower() for keyword in fact_keywords):
        await extract_facts_from_conversation(project_uuid, user_message, answer)
    
    # Rights invocation logging
    article_number = await detect_rights_invocation(draft_answer)
    if article_number:
        try:
            article_row = await pool.fetchrow("SELECT one_sentence_right FROM constitution_rights WHERE article_number = $1", article_number)
            article_text = article_row["one_sentence_right"] if article_row else f"Article {article_number}"
            await log_rights_invocation(project_uuid, article_number, article_text, user_message, draft_answer)
        except Exception as e:
            logger.error(f"Failed to log rights invocation: {e}")
    
    response = ChatResponse(
        project_id=project_id, 
        response=answer, 
        reasoning_trace=reasoning_trace if not error else {"error": True},
        message_id=message_uuid
    )
    json_response = JSONResponse(content=response.dict())
    if session_id:
        json_response.set_cookie(key="session_id", value=session_id, max_age=31536000, httponly=True)
    
    return json_response

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
