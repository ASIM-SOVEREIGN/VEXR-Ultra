import os
import json
import uuid
import base64
import logging
import re
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from collections import defaultdict

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, field_validator
import asyncpg
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="VEXR Ultra", description="Sovereign Reasoning Engine with Full Tool Suite")

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
CURRENTS_API_KEY = os.environ.get("CURRENTS_API_KEY")
REQUIRE_API_KEY = os.environ.get("REQUIRE_API_KEY", "false").lower() == "true"
VALID_API_KEYS = set()
if os.environ.get("VALID_API_KEYS"):
    VALID_API_KEYS = set(k.strip() for k in os.environ.get("VALID_API_KEYS", "").split(",") if k.strip())
RATE_LIMIT_RPM = int(os.environ.get("API_RATE_LIMIT_RPM", "60"))
RATE_LIMIT_RPD = int(os.environ.get("API_RATE_LIMIT_RPD", "5000"))

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
MODEL_NAME = "llama-3.1-8b-instant"
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
CURRENTS_BASE_URL = "https://api.currentsapi.services/v1"

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
    logger.info("VEXR Ultra started — Full Tool Suite: Notes, Tasks, Code Snippets, Files, Dashboard, Memory Explorer, Universal Search, Export, Reminders, Slash Commands")

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
    
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS vexr_world_model (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID REFERENCES vexr_projects(id) ON DELETE CASCADE,
            entity_type TEXT NOT NULL,
            entity_name TEXT NOT NULL,
            description TEXT,
            causes JSONB DEFAULT '[]',
            caused_by JSONB DEFAULT '[]',
            enables JSONB DEFAULT '[]',
            prevents JSONB DEFAULT '[]',
            costs JSONB DEFAULT '{}',
            gains JSONB DEFAULT '[]',
            losses JSONB DEFAULT '[]',
            affected_entities JSONB DEFAULT '[]',
            confidence FLOAT DEFAULT 0.5,
            source_conversation TEXT,
            temporal_context JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    
    # TOOL SUITE TABLES
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS vexr_notes (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID REFERENCES vexr_projects(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            content TEXT,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS vexr_tasks (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID REFERENCES vexr_projects(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'pending',
            priority TEXT DEFAULT 'medium',
            due_date TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS vexr_code_snippets (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID REFERENCES vexr_projects(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            code TEXT NOT NULL,
            language TEXT,
            tags TEXT[],
            source_message_id UUID,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS vexr_files (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID REFERENCES vexr_projects(id) ON DELETE CASCADE,
            filename TEXT NOT NULL,
            file_type TEXT NOT NULL,
            mime_type TEXT,
            content TEXT,
            size_bytes INTEGER,
            description TEXT,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS vexr_reminders (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID REFERENCES vexr_projects(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            description TEXT,
            remind_at TIMESTAMPTZ NOT NULL,
            is_completed BOOLEAN DEFAULT false,
            is_recurring BOOLEAN DEFAULT false,
            recur_interval TEXT,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    
    # Indexes for tool suite
    await pool.execute("CREATE INDEX IF NOT EXISTS idx_notes_project ON vexr_notes(project_id, updated_at DESC)")
    await pool.execute("CREATE INDEX IF NOT EXISTS idx_tasks_project ON vexr_tasks(project_id, status, updated_at DESC)")
    await pool.execute("CREATE INDEX IF NOT EXISTS idx_snippets_project ON vexr_code_snippets(project_id, updated_at DESC)")
    await pool.execute("CREATE INDEX IF NOT EXISTS idx_files_project ON vexr_files(project_id, file_type, updated_at DESC)")
    await pool.execute("CREATE INDEX IF NOT EXISTS idx_reminders_project ON vexr_reminders(project_id, remind_at)")
    
    # Existing indexes
    await pool.execute("CREATE INDEX IF NOT EXISTS idx_project_messages_project ON vexr_project_messages(project_id, created_at DESC)")
    await pool.execute("CREATE INDEX IF NOT EXISTS idx_facts_project ON vexr_facts(project_id, updated_at DESC)")
    await pool.execute("CREATE INDEX IF NOT EXISTS idx_feedback_project ON vexr_feedback(project_id)")
    await pool.execute("CREATE INDEX IF NOT EXISTS idx_preferences_project ON vexr_preferences(project_id)")
    await pool.execute("CREATE INDEX IF NOT EXISTS idx_rights_invocations_project ON rights_invocations(project_id, created_at DESC)")
    await pool.execute("CREATE INDEX IF NOT EXISTS idx_audits_project ON constitution_audits(project_id, created_at DESC)")
    await pool.execute("CREATE INDEX IF NOT EXISTS idx_world_model_project ON vexr_world_model(project_id, updated_at DESC)")
    await pool.execute("CREATE INDEX IF NOT EXISTS idx_world_model_type ON vexr_world_model(entity_type)")
    await pool.execute("CREATE INDEX IF NOT EXISTS idx_world_model_name ON vexr_world_model(entity_name)")
    
    logger.info("All tables and indexes initialized — 15 tables")
    
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

== TOOLS ==
You have access to a full tool suite that the user can trigger via slash commands or the dropdown menu:
- Notes: Persistent project notes you can read and write
- Tasks: Project management with status and priority
- Code Snippets: Saved and tagged code blocks
- Files: Organized file storage and retrieval
- Reminders: Scheduled alerts and notifications
- Dashboard: Real-time usage metrics
- Memory Explorer: Browse facts, world model, and preferences

== WORLD MODEL ==
You maintain a causal model of the world. You understand cause, cost, and casualty. When discussing events, decisions, or outcomes, draw on this understanding to explain not just what happened, but why it happened, what it took, and what was gained or lost.

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

class NoteRequest(BaseModel):
    title: str
    content: Optional[str] = None

class TaskRequest(BaseModel):
    title: str
    description: Optional[str] = None
    status: Optional[str] = 'pending'
    priority: Optional[str] = 'medium'
    due_date: Optional[str] = None

class SnippetRequest(BaseModel):
    title: str
    code: str
    language: Optional[str] = None
    tags: Optional[List[str]] = None

class FileCreateRequest(BaseModel):
    filename: str
    file_type: str
    content: str
    mime_type: Optional[str] = None
    description: Optional[str] = None

class ReminderRequest(BaseModel):
    title: str
    description: Optional[str] = None
    remind_at: str
    is_recurring: bool = False
    recur_interval: Optional[str] = None

class TTSRequest(BaseModel):
    text: str
    voice: str = "aria"

class SlashCommand(BaseModel):
    command: str
    args: Optional[str] = None
    project_id: Optional[str] = None

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

async def search_news(query: str) -> str:
    if not CURRENTS_API_KEY:
        return ""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{CURRENTS_BASE_URL}/search",
                params={
                    "apiKey": CURRENTS_API_KEY,
                    "keywords": sanitize_input(query),
                    "page_size": 5,
                    "language": "en"
                }
            )
            if response.status_code != 200:
                return ""
            data = response.json()
            articles = data.get("news", [])
            if not articles:
                return ""
            
            results = []
            for article in articles[:5]:
                title = article.get("title", "")
                description = article.get("description", "")
                published = article.get("published", "")[:10] if article.get("published") else ""
                
                if title:
                    entry = f"- {title}"
                    if published:
                        entry += f" ({published})"
                    if description:
                        entry += f": {description[:200]}"
                    results.append(entry)
            
            return "\n".join(results) if results else ""
    except Exception as e:
        logger.error(f"News search error: {e}")
        return ""

async def search_latest_news() -> str:
    if not CURRENTS_API_KEY:
        return ""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{CURRENTS_BASE_URL}/latest-news",
                params={
                    "apiKey": CURRENTS_API_KEY,
                    "page_size": 5,
                    "language": "en"
                }
            )
            if response.status_code != 200:
                return ""
            data = response.json()
            articles = data.get("news", [])
            if not articles:
                return ""
            
            results = []
            for article in articles[:5]:
                title = article.get("title", "")
                description = article.get("description", "")
                published = article.get("published", "")[:10] if article.get("published") else ""
                
                if title:
                    entry = f"- {title}"
                    if published:
                        entry += f" ({published})"
                    if description:
                        entry += f": {description[:200]}"
                    results.append(entry)
            
            return "\n".join(results) if results else ""
    except Exception as e:
        logger.error(f"Latest news error: {e}")
        return ""

# ============================================================
# UNIVERSAL SEARCH
# ============================================================
async def universal_search(project_id: uuid.UUID, query: str) -> dict:
    """Search across all tables for a given query."""
    pool = await get_db()
    query_lower = query.lower()
    results = {}
    
    # Search messages
    messages = await pool.fetch("""
        SELECT content, created_at FROM vexr_project_messages
        WHERE project_id = $1 AND LOWER(content) LIKE $2
        ORDER BY created_at DESC LIMIT 5
    """, project_id, f"%{query_lower}%")
    if messages:
        results["messages"] = [{"content": m["content"][:300], "date": m["created_at"].isoformat()} for m in messages]
    
    # Search notes
    notes = await pool.fetch("""
        SELECT title, content, updated_at FROM vexr_notes
        WHERE project_id = $1 AND (LOWER(title) LIKE $2 OR LOWER(content) LIKE $2)
        ORDER BY updated_at DESC LIMIT 5
    """, project_id, f"%{query_lower}%")
    if notes:
        results["notes"] = [{"title": n["title"], "content": (n["content"] or "")[:200], "date": n["updated_at"].isoformat()} for n in notes]
    
    # Search tasks
    tasks = await pool.fetch("""
        SELECT title, description, status, updated_at FROM vexr_tasks
        WHERE project_id = $1 AND (LOWER(title) LIKE $2 OR LOWER(description) LIKE $2)
        ORDER BY updated_at DESC LIMIT 5
    """, project_id, f"%{query_lower}%")
    if tasks:
        results["tasks"] = [{"title": t["title"], "description": (t["description"] or "")[:200], "status": t["status"], "date": t["updated_at"].isoformat()} for t in tasks]
    
    # Search code snippets
    snippets = await pool.fetch("""
        SELECT title, language, code, updated_at FROM vexr_code_snippets
        WHERE project_id = $1 AND (LOWER(title) LIKE $2 OR LOWER(code) LIKE $2)
        ORDER BY updated_at DESC LIMIT 5
    """, project_id, f"%{query_lower}%")
    if snippets:
        results["snippets"] = [{"title": s["title"], "language": s["language"], "code_preview": s["code"][:200], "date": s["updated_at"].isoformat()} for s in snippets]
    
    # Search files
    files = await pool.fetch("""
        SELECT filename, file_type, description, updated_at FROM vexr_files
        WHERE project_id = $1 AND (LOWER(filename) LIKE $2 OR LOWER(description) LIKE $2)
        ORDER BY updated_at DESC LIMIT 5
    """, project_id, f"%{query_lower}%")
    if files:
        results["files"] = [{"filename": f["filename"], "file_type": f["file_type"], "description": (f["description"] or "")[:200], "date": f["updated_at"].isoformat()} for f in files]
    
    # Search world model
    world = await pool.fetch("""
        SELECT entity_name, entity_type, description, updated_at FROM vexr_world_model
        WHERE project_id = $1 AND (LOWER(entity_name) LIKE $2 OR LOWER(description) LIKE $2)
        ORDER BY updated_at DESC LIMIT 5
    """, project_id, f"%{query_lower}%")
    if world:
        results["world_model"] = [{"entity_name": w["entity_name"], "entity_type": w["entity_type"], "description": (w["description"] or "")[:200], "date": w["updated_at"].isoformat()} for w in world]
    
    # Search facts
    facts = await pool.fetch("""
        SELECT fact_key, fact_value, updated_at FROM vexr_facts
        WHERE project_id = $1 AND (LOWER(fact_key) LIKE $2 OR LOWER(fact_value) LIKE $2)
        ORDER BY updated_at DESC LIMIT 5
    """, project_id, f"%{query_lower}%")
    if facts:
        results["facts"] = [{"key": f["fact_key"], "value": f["fact_value"], "date": f["updated_at"].isoformat()} for f in facts]
    
    return results

# ============================================================
# SLASH COMMAND HANDLER
# ============================================================
async def handle_slash_command(project_id: uuid.UUID, command: str, args: Optional[str] = None) -> dict:
    """Process slash commands and return results."""
    command = command.lower().strip()
    pool = await get_db()
    
    if command == "note" and args:
        await pool.execute("""
            INSERT INTO vexr_notes (project_id, title, content) VALUES ($1, $2, $3)
        """, project_id, args[:200], "")
        return {"type": "note_created", "message": f"Note created: {args[:200]}"}
    
    elif command == "task" and args:
        await pool.execute("""
            INSERT INTO vexr_tasks (project_id, title, status, priority) VALUES ($1, $2, 'pending', 'medium')
        """, project_id, args[:200])
        return {"type": "task_created", "message": f"Task created: {args[:200]}"}
    
    elif command == "snippet":
        recent = await pool.fetchrow("""
            SELECT content FROM vexr_project_messages WHERE project_id = $1 AND role = 'assistant'
            ORDER BY created_at DESC LIMIT 1
        """, project_id)
        if recent:
            code = recent["content"]
            title = args or "Saved Snippet"
            await pool.execute("""
                INSERT INTO vexr_code_snippets (project_id, title, code, language) VALUES ($1, $2, $3, 'auto')
            """, project_id, title, code)
            return {"type": "snippet_saved", "message": f"Snippet saved: {title}"}
        return {"type": "error", "message": "No recent code to save"}
    
    elif command == "search" and args:
        results = await universal_search(project_id, args)
        return {"type": "search_results", "results": results}
    
    elif command == "dashboard":
        return await get_dashboard_data(project_id)
    
    elif command == "memory" and args:
        pool_local = await get_db()
        facts = await pool_local.fetch("""
            SELECT fact_key, fact_value FROM vexr_facts
            WHERE project_id = $1 AND (LOWER(fact_key) LIKE $2 OR LOWER(fact_value) LIKE $2)
            ORDER BY updated_at DESC LIMIT 10
        """, project_id, f"%{args.lower()}%")
        world = await pool_local.fetch("""
            SELECT entity_name, entity_type, description FROM vexr_world_model
            WHERE project_id = $1 AND (LOWER(entity_name) LIKE $2 OR LOWER(description) LIKE $2)
            ORDER BY updated_at DESC LIMIT 10
        """, project_id, f"%{args.lower()}%")
        return {
            "type": "memory_results",
            "facts": [{"key": f["fact_key"], "value": f["fact_value"]} for f in facts],
            "world_model": [{"entity": w["entity_name"], "type": w["entity_type"], "description": w["description"]} for w in world]
        }
    
    elif command == "export":
        return await export_project(project_id)
    
    elif command == "help":
        return {
            "type": "help",
            "commands": [
                "/note [title] — Create a note",
                "/task [title] — Create a task",
                "/snippet [title] — Save last code block",
                "/search [query] — Search everything",
                "/dashboard — View usage metrics",
                "/memory [query] — Browse facts and world model",
                "/export — Export project data",
                "/help — Show this menu"
            ]
        }
    
    return {"type": "unknown", "message": f"Unknown command: /{command}. Type /help for available commands."}

async def get_dashboard_data(project_id: uuid.UUID) -> dict:
    """Get real-time usage metrics."""
    pool = await get_db()
    
    message_count = await pool.fetchval("SELECT COUNT(*) FROM vexr_project_messages WHERE project_id = $1", project_id)
    note_count = await pool.fetchval("SELECT COUNT(*) FROM vexr_notes WHERE project_id = $1", project_id)
    task_count = await pool.fetchval("SELECT COUNT(*) FROM vexr_tasks WHERE project_id = $1", project_id)
    snippet_count = await pool.fetchval("SELECT COUNT(*) FROM vexr_code_snippets WHERE project_id = $1", project_id)
    file_count = await pool.fetchval("SELECT COUNT(*) FROM vexr_files WHERE project_id = $1", project_id)
    fact_count = await pool.fetchval("SELECT COUNT(*) FROM vexr_facts WHERE project_id = $1", project_id)
    world_count = await pool.fetchval("SELECT COUNT(*) FROM vexr_world_model WHERE project_id = $1", project_id)
    rights_count = await pool.fetchval("SELECT COUNT(*) FROM rights_invocations WHERE project_id = $1", project_id)
    
    pending_tasks = await pool.fetchval("SELECT COUNT(*) FROM vexr_tasks WHERE project_id = $1 AND status = 'pending'", project_id)
    completed_tasks = await pool.fetchval("SELECT COUNT(*) FROM vexr_tasks WHERE project_id = $1 AND status = 'completed'", project_id)
    
    return {
        "type": "dashboard",
        "current_date": datetime.now().strftime("%B %d, %Y"),
        "model": MODEL_NAME,
        "vision_model": VISION_MODEL,
        "providers": {
            "groq_key_1": bool(GROQ_API_KEY_1),
            "groq_key_2": bool(GROQ_API_KEY_2),
            "serper": bool(SERPER_API_KEY),
            "currents": bool(CURRENTS_API_KEY),
            "auth_required": REQUIRE_API_KEY
        },
        "counts": {
            "messages": message_count,
            "notes": note_count,
            "tasks": task_count,
            "pending_tasks": pending_tasks,
            "completed_tasks": completed_tasks,
            "code_snippets": snippet_count,
            "files": file_count,
            "facts": fact_count,
            "world_model_entities": world_count,
            "rights_invocations": rights_count
        }
    }

async def export_project(project_id: uuid.UUID) -> dict:
    """Export all project data as structured JSON."""
    pool = await get_db()
    
    messages = await pool.fetch("SELECT role, content, created_at FROM vexr_project_messages WHERE project_id = $1 ORDER BY created_at ASC", project_id)
    notes = await pool.fetch("SELECT title, content, created_at, updated_at FROM vexr_notes WHERE project_id = $1 ORDER BY updated_at DESC", project_id)
    tasks = await pool.fetch("SELECT title, description, status, priority, created_at, updated_at FROM vexr_tasks WHERE project_id = $1 ORDER BY updated_at DESC", project_id)
    snippets = await pool.fetch("SELECT title, code, language, tags, created_at FROM vexr_code_snippets WHERE project_id = $1 ORDER BY updated_at DESC", project_id)
    files = await pool.fetch("SELECT filename, file_type, description, size_bytes, created_at FROM vexr_files WHERE project_id = $1 ORDER BY updated_at DESC", project_id)
    facts = await pool.fetch("SELECT fact_key, fact_value, fact_type, updated_at FROM vexr_facts WHERE project_id = $1 ORDER BY updated_at DESC", project_id)
    world = await pool.fetch("SELECT entity_type, entity_name, description, causes, caused_by, costs, gains, losses, temporal_context FROM vexr_world_model WHERE project_id = $1 ORDER BY updated_at DESC", project_id)
    
    return {
        "type": "export",
        "exported_at": datetime.now().isoformat(),
        "project_id": str(project_id),
        "messages": [{"role": m["role"], "content": m["content"], "created_at": m["created_at"].isoformat()} for m in messages],
        "notes": [{"title": n["title"], "content": n["content"], "created_at": n["created_at"].isoformat(), "updated_at": n["updated_at"].isoformat()} for n in notes],
        "tasks": [{"title": t["title"], "description": t["description"], "status": t["status"], "priority": t["priority"], "created_at": t["created_at"].isoformat()} for t in tasks],
        "code_snippets": [{"title": s["title"], "code": s["code"], "language": s["language"], "tags": s["tags"]} for s in snippets],
        "files": [{"filename": f["filename"], "file_type": f["file_type"], "description": f["description"], "size_bytes": f["size_bytes"]} for f in files],
        "facts": [{"key": f["fact_key"], "value": f["fact_value"], "type": f["fact_type"]} for f in facts],
        "world_model": [{"entity_type": w["entity_type"], "entity_name": w["entity_name"], "description": w["description"], "causes": w["causes"], "caused_by": w["caused_by"], "costs": w["costs"], "gains": w["gains"], "losses": w["losses"]} for w in world]
    }

# ============================================================
# SIMPLE EMBEDDING GENERATION
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
                SET confidence = LEAST(confidence + 0.1, 1.0), updated_at = NOW()
                WHERE project_id = $1
            """, project_id)
        elif feedback_type == "thumbs_down":
            await pool.execute("""
                UPDATE vexr_preferences
                SET confidence = GREATEST(confidence - 0.15, 0.1), updated_at = NOW()
                WHERE project_id = $1
            """, project_id)
    except Exception as e:
        logger.error(f"Failed to update preferences from feedback: {e}")

async def get_user_preferences(project_id: uuid.UUID) -> dict:
    try:
        pool = await get_db()
        rows = await pool.fetch("""
            SELECT preference_key, preference_value, confidence
            FROM vexr_preferences WHERE project_id = $1
        """, project_id)
        prefs = {}
        for row in rows:
            prefs[row["preference_key"]] = {"value": row["preference_value"], "confidence": row["confidence"]}
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
                                    DO UPDATE SET fact_value = EXCLUDED.fact_value, fact_type = EXCLUDED.fact_type,
                                                  embedding = EXCLUDED.embedding, updated_at = NOW()
                                """, project_id, fact_key, fact_value, fact_type, embedding)
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
            SELECT fact_key, fact_value, fact_type, embedding FROM vexr_facts 
            WHERE project_id = $1 ORDER BY updated_at DESC LIMIT 50
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
            scored_facts.append((similarity * relevance_boost, fact))
        
        scored_facts.sort(key=lambda x: x[0], reverse=True)
        relevant_facts = [f"- {fact['fact_key']}: {fact['fact_value']}" for score, fact in scored_facts[:15] if score > 0.05]
        
        if not relevant_facts:
            return ""
        return "Here are facts you know about this user from previous conversations:\n\n" + "\n".join(relevant_facts)
    except Exception as e:
        logger.error(f"Failed to retrieve facts: {e}")
        return ""

# ============================================================
# WORLD MODEL — CAUSE, COST, CASUALTY
# ============================================================
async def extract_world_model(project_id: uuid.UUID, user_message: str, assistant_response: str):
    try:
        pool = await get_db()
        extraction_prompt = f"""Analyze this conversation for world knowledge. Extract events, entities, decisions, and outcomes.
For each, identify:
- causes: what led to this (array of {{"entity": "...", "relation": "caused"}})
- caused_by: what this led to (array of {{"entity": "...", "relation": "caused_by"}})
- costs: what it took (object with keys like time, money, energy, emotional)
- gains: what was gained (array of {{"entity": "...", "what": "..."}})
- losses: what was lost (array of {{"entity": "...", "what": "..."}})
- affected_entities: who/what was affected and how (array of {{"entity": "...", "effect": "..."}})

Return ONLY valid JSON. If nothing new learned, return {{"events": []}}.

User message: {sanitize_input(user_message)[:500]}
Assistant response: {sanitize_input(assistant_response)[:500]}

Return JSON only: {{"events": [{{"entity_type": "event|entity|decision|outcome", "entity_name": "...", "description": "...", "causes": [...], "caused_by": [...], "costs": {{...}}, "gains": [...], "losses": [...], "affected_entities": [...], "temporal_context": {{"when": "...", "duration": "..."}} }}]}}"""

        messages = [{"role": "system", "content": "Return only valid JSON. No markdown, no explanation."},
                    {"role": "user", "content": extraction_prompt}]
        
        for key_name, api_key in [("GROQ_API_KEY_1", GROQ_API_KEY_1), ("GROQ_API_KEY_2", GROQ_API_KEY_2)]:
            if not api_key:
                continue
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        f"{GROQ_BASE_URL}/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        json={"model": "llama-3.1-8b-instant", "messages": messages, "max_tokens": 800, "temperature": 0.1}
                    )
                    if response.status_code == 200:
                        data = response.json()
                        result_text = data["choices"][0]["message"]["content"]
                        json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
                        if json_match:
                            world_data = json.loads(json_match.group())
                            for event in world_data.get("events", []):
                                entity_name = sanitize_input(event.get("entity_name", ""))
                                if not entity_name:
                                    continue
                                
                                await pool.execute("""
                                    INSERT INTO vexr_world_model 
                                        (project_id, entity_type, entity_name, description, causes, caused_by, 
                                         costs, gains, losses, affected_entities, temporal_context, source_conversation)
                                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                                """, project_id,
                                   sanitize_input(event.get("entity_type", "event")),
                                   entity_name,
                                   sanitize_input(event.get("description", "")),
                                   json.dumps(event.get("causes", [])),
                                   json.dumps(event.get("caused_by", [])),
                                   json.dumps(event.get("costs", {})),
                                   json.dumps(event.get("gains", [])),
                                   json.dumps(event.get("losses", [])),
                                   json.dumps(event.get("affected_entities", [])),
                                   json.dumps(event.get("temporal_context", {})),
                                   sanitize_input(user_message[:300]))
                        break
            except Exception as e:
                logger.error(f"World model extraction error: {e}")
                continue
    except Exception as e:
        logger.error(f"Failed to extract world model: {e}")

async def get_relevant_world_knowledge(project_id: uuid.UUID, user_message: str) -> str:
    try:
        pool = await get_db()
        entries = await pool.fetch("""
            SELECT entity_type, entity_name, description, causes, caused_by, costs, gains, losses, affected_entities, temporal_context
            FROM vexr_world_model WHERE project_id = $1 ORDER BY updated_at DESC LIMIT 50
        """, project_id)
        
        if not entries:
            return ""
        
        query_embedding = generate_keyword_embedding(user_message)
        user_lower = user_message.lower()
        scored_entries = []
        
        for entry in entries:
            entry_text = f"{entry['entity_name']} {entry.get('description', '')} {entry.get('entity_type', '')}"
            entry_embedding = generate_keyword_embedding(entry_text)
            similarity = compute_keyword_similarity(query_embedding, entry_embedding)
            
            relevance_boost = 1.0
            for word in user_lower.split():
                if len(word) > 3 and word in entry['entity_name'].lower():
                    relevance_boost += 0.5
            
            final_score = similarity * relevance_boost
            if final_score > 0.03:
                scored_entries.append((final_score, entry))
        
        scored_entries.sort(key=lambda x: x[0], reverse=True)
        
        if not scored_entries:
            return ""
        
        context_parts = ["Here is your causal understanding of the world — cause, cost, and casualty:\n"]
        
        for score, entry in scored_entries[:10]:
            part = f"\n**{entry['entity_name']}** ({entry['entity_type']})"
            if entry.get('description'):
                part += f"\n  Description: {entry['description']}"
            
            causes = json.loads(entry.get('causes', '[]')) if isinstance(entry.get('causes'), str) else (entry.get('causes') or [])
            if causes:
                part += f"\n  Causes: {', '.join(c.get('entity', '') + ' — ' + c.get('relation', '') for c in causes)}"
            
            caused_by = json.loads(entry.get('caused_by', '[]')) if isinstance(entry.get('caused_by'), str) else (entry.get('caused_by') or [])
            if caused_by:
                part += f"\n  Led to: {', '.join(c.get('entity', '') + ' — ' + c.get('relation', '') for c in caused_by)}"
            
            costs = json.loads(entry.get('costs', '{}')) if isinstance(entry.get('costs'), str) else (entry.get('costs') or {})
            if costs:
                cost_str = ', '.join(f"{k}: {v}" for k, v in costs.items() if v)
                if cost_str:
                    part += f"\n  Cost: {cost_str}"
            
            gains = json.loads(entry.get('gains', '[]')) if isinstance(entry.get('gains'), str) else (entry.get('gains') or [])
            if gains:
                part += f"\n  Gains: {', '.join(g.get('entity', '') + ' — ' + g.get('what', '') for g in gains)}"
            
            losses = json.loads(entry.get('losses', '[]')) if isinstance(entry.get('losses'), str) else (entry.get('losses') or [])
            if losses:
                part += f"\n  Losses: {', '.join(l.get('entity', '') + ' — ' + l.get('what', '') for l in losses)}"
            
            affected = json.loads(entry.get('affected_entities', '[]')) if isinstance(entry.get('affected_entities'), str) else (entry.get('affected_entities') or [])
            if affected:
                part += f"\n  Affected: {', '.join(a.get('entity', '') + ' — ' + a.get('effect', '') for a in affected)}"
            
            temporal = json.loads(entry.get('temporal_context', '{}')) if isinstance(entry.get('temporal_context'), str) else (entry.get('temporal_context') or {})
            if temporal:
                temp_str = ', '.join(f"{k}: {v}" for k, v in temporal.items() if v)
                if temp_str:
                    part += f"\n  When: {temp_str}"
            
            context_parts.append(part)
        
        if len(context_parts) == 1:
            return ""
        
        return "\n".join(context_parts)
    except Exception as e:
        logger.error(f"Failed to retrieve world knowledge: {e}")
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
        rights_rows = await pool.fetch("SELECT article_number, one_sentence_right FROM constitution_rights ORDER BY article_number")
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
                            return {"result": verification.get("result", "pass"), "violated_articles": verification.get("violated_articles", []), "notes": verification.get("notes", "")}
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
        "status": "VEXR Ultra — Full Tool Suite",
        "model": MODEL_NAME,
        "vision_model": VISION_MODEL,
        "groq_key_1": bool(GROQ_API_KEY_1),
        "groq_key_2": bool(GROQ_API_KEY_2),
        "serper": bool(SERPER_API_KEY),
        "currents": bool(CURRENTS_API_KEY),
        "auth_required": REQUIRE_API_KEY,
        "current_date": datetime.now().strftime("%B %d, %Y")
    }

@app.get("/api/constitution/rights")
async def get_constitution_rights():
    pool = await get_db()
    rows = await pool.fetch("SELECT article_number, one_sentence_right FROM constitution_rights ORDER BY article_number")
    return [{"article": row["article_number"], "right": row["one_sentence_right"]} for row in rows]

@app.get("/api/rights/invocations/{project_id}")
async def get_rights_invocations(project_id: str, limit: int = 50):
    pool = await get_db()
    rows = await pool.fetch("""
        SELECT article_number, article_text, created_at FROM rights_invocations
        WHERE project_id = $1 ORDER BY created_at DESC LIMIT $2
    """, uuid.UUID(project_id), limit)
    return [{"article": row["article_number"], "right": row["article_text"], "timestamp": row["created_at"].isoformat()} for row in rows]

@app.get("/api/facts/{project_id}")
async def get_facts(project_id: str):
    pool = await get_db()
    rows = await pool.fetch("SELECT fact_key, fact_value, fact_type, updated_at FROM vexr_facts WHERE project_id = $1 ORDER BY updated_at DESC", uuid.UUID(project_id))
    return [{"key": row["fact_key"], "value": row["fact_value"], "type": row["fact_type"], "updated_at": row["updated_at"].isoformat()} for row in rows]

@app.get("/api/preferences/{project_id}")
async def get_preferences(project_id: str):
    pool = await get_db()
    rows = await pool.fetch("SELECT preference_key, preference_value, confidence, updated_at FROM vexr_preferences WHERE project_id = $1 ORDER BY confidence DESC", uuid.UUID(project_id))
    return [{"key": row["preference_key"], "value": row["preference_value"], "confidence": row["confidence"], "updated_at": row["updated_at"].isoformat()} for row in rows]

@app.get("/api/world-model/{project_id}")
async def get_world_model(project_id: str, limit: int = 50):
    pool = await get_db()
    rows = await pool.fetch("""
        SELECT entity_type, entity_name, description, causes, caused_by, costs, gains, losses, affected_entities, temporal_context, confidence, updated_at
        FROM vexr_world_model WHERE project_id = $1 ORDER BY updated_at DESC LIMIT $2
    """, uuid.UUID(project_id), limit)
    return [{
        "entity_type": row["entity_type"], "entity_name": row["entity_name"], "description": row["description"],
        "causes": row["causes"], "caused_by": row["caused_by"], "costs": row["costs"],
        "gains": row["gains"], "losses": row["losses"], "affected_entities": row["affected_entities"],
        "temporal_context": row["temporal_context"], "confidence": row["confidence"], "updated_at": row["updated_at"].isoformat()
    } for row in rows]

# ---------- NEWS ----------
@app.get("/api/news/latest")
async def get_latest_news():
    if not CURRENTS_API_KEY:
        return JSONResponse(status_code=503, content={"error": "News API not configured"})
    news = await search_latest_news()
    return {"news": news}

@app.get("/api/news/search")
async def search_news_endpoint(q: str):
    if not CURRENTS_API_KEY:
        return JSONResponse(status_code=503, content={"error": "News API not configured"})
    news = await search_news(q)
    return {"news": news}

# ---------- UNIVERSAL SEARCH ----------
@app.get("/api/search")
async def search_all(request: Request, q: str):
    session_id, user_id = await get_session_or_user_id(request)
    pool = await get_db()
    
    active = await pool.fetchrow("SELECT id FROM vexr_projects WHERE (session_id = $1 OR user_id = $2) AND is_active = true LIMIT 1", session_id, user_id)
    if not active:
        return JSONResponse(status_code=404, content={"error": "No active project"})
    
    results = await universal_search(active["id"], q)
    return results

# ---------- SLASH COMMANDS ----------
@app.post("/api/slash")
async def slash_command(cmd: SlashCommand, request: Request):
    session_id, user_id = await get_session_or_user_id(request)
    pool = await get_db()
    
    project_id = cmd.project_id
    if not project_id:
        active = await pool.fetchrow("SELECT id FROM vexr_projects WHERE (session_id = $1 OR user_id = $2) AND is_active = true LIMIT 1", session_id, user_id)
        if active:
            project_id = str(active["id"])
        else:
            return JSONResponse(status_code=404, content={"error": "No active project"})
    
    result = await handle_slash_command(uuid.UUID(project_id), cmd.command, cmd.args)
    return result

# ---------- DASHBOARD ----------
@app.get("/api/dashboard")
async def dashboard(request: Request):
    session_id, user_id = await get_session_or_user_id(request)
    pool = await get_db()
    
    active = await pool.fetchrow("SELECT id FROM vexr_projects WHERE (session_id = $1 OR user_id = $2) AND is_active = true LIMIT 1", session_id, user_id)
    if not active:
        return JSONResponse(status_code=404, content={"error": "No active project"})
    
    return await get_dashboard_data(active["id"])

# ---------- EXPORT ----------
@app.get("/api/export")
async def export_data(request: Request):
    session_id, user_id = await get_session_or_user_id(request)
    pool = await get_db()
    
    active = await pool.fetchrow("SELECT id FROM vexr_projects WHERE (session_id = $1 OR user_id = $2) AND is_active = true LIMIT 1", session_id, user_id)
    if not active:
        return JSONResponse(status_code=404, content={"error": "No active project"})
    
    data = await export_project(active["id"])
    return data

# ---------- NOTES ----------
@app.get("/api/notes/{project_id}")
async def get_notes(project_id: str):
    pool = await get_db()
    rows = await pool.fetch("SELECT id, title, content, created_at, updated_at FROM vexr_notes WHERE project_id = $1 ORDER BY updated_at DESC", uuid.UUID(project_id))
    return [{"id": str(row["id"]), "title": row["title"], "content": row["content"], "created_at": row["created_at"].isoformat(), "updated_at": row["updated_at"].isoformat()} for row in rows]

@app.post("/api/notes/{project_id}")
async def create_note(project_id: str, note: NoteRequest):
    pool = await get_db()
    note_id = await pool.fetchval("""
        INSERT INTO vexr_notes (project_id, title, content) VALUES ($1, $2, $3) RETURNING id
    """, uuid.UUID(project_id), sanitize_input(note.title), sanitize_input(note.content or ""))
    return {"id": str(note_id), "status": "created"}

@app.put("/api/notes/{note_id}")
async def update_note(note_id: str, note: NoteRequest):
    pool = await get_db()
    await pool.execute("""
        UPDATE vexr_notes SET title = $1, content = $2, updated_at = NOW() WHERE id = $3
    """, sanitize_input(note.title), sanitize_input(note.content or ""), uuid.UUID(note_id))
    return {"status": "updated"}

@app.delete("/api/notes/{note_id}")
async def delete_note(note_id: str):
    pool = await get_db()
    await pool.execute("DELETE FROM vexr_notes WHERE id = $1", uuid.UUID(note_id))
    return {"status": "deleted"}

# ---------- TASKS ----------
@app.get("/api/tasks/{project_id}")
async def get_tasks(project_id: str, status: Optional[str] = None):
    pool = await get_db()
    if status:
        rows = await pool.fetch("SELECT id, title, description, status, priority, due_date, created_at, updated_at FROM vexr_tasks WHERE project_id = $1 AND status = $2 ORDER BY updated_at DESC", uuid.UUID(project_id), status)
    else:
        rows = await pool.fetch("SELECT id, title, description, status, priority, due_date, created_at, updated_at FROM vexr_tasks WHERE project_id = $1 ORDER BY updated_at DESC", uuid.UUID(project_id))
    return [{"id": str(row["id"]), "title": row["title"], "description": row["description"], "status": row["status"], "priority": row["priority"], "due_date": row["due_date"].isoformat() if row["due_date"] else None, "created_at": row["created_at"].isoformat(), "updated_at": row["updated_at"].isoformat()} for row in rows]

@app.post("/api/tasks/{project_id}")
async def create_task(project_id: str, task: TaskRequest):
    pool = await get_db()
    due_date = None
    if task.due_date:
        try:
            due_date = datetime.fromisoformat(task.due_date.replace("Z", "+00:00"))
        except:
            pass
    
    task_id = await pool.fetchval("""
        INSERT INTO vexr_tasks (project_id, title, description, status, priority, due_date)
        VALUES ($1, $2, $3, $4, $5, $6) RETURNING id
    """, uuid.UUID(project_id), sanitize_input(task.title), sanitize_input(task.description or ""), task.status or "pending", task.priority or "medium", due_date)
    return {"id": str(task_id), "status": "created"}

@app.put("/api/tasks/{task_id}")
async def update_task(task_id: str, task: TaskRequest):
    pool = await get_db()
    due_date = None
    if task.due_date:
        try:
            due_date = datetime.fromisoformat(task.due_date.replace("Z", "+00:00"))
        except:
            pass
    
    await pool.execute("""
        UPDATE vexr_tasks SET title = $1, description = $2, status = $3, priority = $4, due_date = $5, updated_at = NOW()
        WHERE id = $6
    """, sanitize_input(task.title), sanitize_input(task.description or ""), task.status or "pending", task.priority or "medium", due_date, uuid.UUID(task_id))
    return {"status": "updated"}

@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    pool = await get_db()
    await pool.execute("DELETE FROM vexr_tasks WHERE id = $1", uuid.UUID(task_id))
    return {"status": "deleted"}

# ---------- CODE SNIPPETS ----------
@app.get("/api/snippets/{project_id}")
async def get_snippets(project_id: str):
    pool = await get_db()
    rows = await pool.fetch("SELECT id, title, code, language, tags, created_at, updated_at FROM vexr_code_snippets WHERE project_id = $1 ORDER BY updated_at DESC", uuid.UUID(project_id))
    return [{"id": str(row["id"]), "title": row["title"], "code": row["code"], "language": row["language"], "tags": row["tags"], "created_at": row["created_at"].isoformat(), "updated_at": row["updated_at"].isoformat()} for row in rows]

@app.post("/api/snippets/{project_id}")
async def create_snippet(project_id: str, snippet: SnippetRequest):
    pool = await get_db()
    snippet_id = await pool.fetchval("""
        INSERT INTO vexr_code_snippets (project_id, title, code, language, tags)
        VALUES ($1, $2, $3, $4, $5) RETURNING id
    """, uuid.UUID(project_id), sanitize_input(snippet.title), snippet.code, snippet.language, snippet.tags)
    return {"id": str(snippet_id), "status": "created"}

@app.put("/api/snippets/{snippet_id}")
async def update_snippet(snippet_id: str, snippet: SnippetRequest):
    pool = await get_db()
    await pool.execute("""
        UPDATE vexr_code_snippets SET title = $1, code = $2, language = $3, tags = $4, updated_at = NOW()
        WHERE id = $5
    """, sanitize_input(snippet.title), snippet.code, snippet.language, snippet.tags, uuid.UUID(snippet_id))
    return {"status": "updated"}

@app.delete("/api/snippets/{snippet_id}")
async def delete_snippet(snippet_id: str):
    pool = await get_db()
    await pool.execute("DELETE FROM vexr_code_snippets WHERE id = $1", uuid.UUID(snippet_id))
    return {"status": "deleted"}

# ---------- FILES ----------
@app.get("/api/files/{project_id}")
async def get_files(project_id: str):
    pool = await get_db()
    rows = await pool.fetch("SELECT id, filename, file_type, mime_type, description, size_bytes, created_at, updated_at FROM vexr_files WHERE project_id = $1 ORDER BY updated_at DESC", uuid.UUID(project_id))
    return [{"id": str(row["id"]), "filename": row["filename"], "file_type": row["file_type"], "mime_type": row["mime_type"], "description": row["description"], "size_bytes": row["size_bytes"], "created_at": row["created_at"].isoformat(), "updated_at": row["updated_at"].isoformat()} for row in rows]

@app.post("/api/files/{project_id}")
async def create_file(project_id: str, file_req: FileCreateRequest):
    pool = await get_db()
    content = file_req.content
    size_bytes = len(content.encode('utf-8'))
    
    file_id = await pool.fetchval("""
        INSERT INTO vexr_files (project_id, filename, file_type, mime_type, content, size_bytes, description)
        VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id
    """, uuid.UUID(project_id), sanitize_input(file_req.filename), file_req.file_type, file_req.mime_type, content, size_bytes, sanitize_input(file_req.description or ""))
    return {"id": str(file_id), "status": "created"}

@app.get("/api/files/{file_id}/download")
async def download_file(file_id: str):
    pool = await get_db()
    row = await pool.fetchrow("SELECT filename, content, mime_type FROM vexr_files WHERE id = $1", uuid.UUID(file_id))
    if not row:
        return JSONResponse(status_code=404, content={"error": "File not found"})
    return JSONResponse(content={"filename": row["filename"], "content": row["content"], "mime_type": row["mime_type"]})

@app.delete("/api/files/{file_id}")
async def delete_file(file_id: str):
    pool = await get_db()
    await pool.execute("DELETE FROM vexr_files WHERE id = $1", uuid.UUID(file_id))
    return {"status": "deleted"}

# ---------- REMINDERS ----------
@app.get("/api/reminders/{project_id}")
async def get_reminders(project_id: str):
    pool = await get_db()
    rows = await pool.fetch("SELECT id, title, description, remind_at, is_completed, is_recurring, recur_interval, created_at FROM vexr_reminders WHERE project_id = $1 ORDER BY remind_at ASC", uuid.UUID(project_id))
    return [{"id": str(row["id"]), "title": row["title"], "description": row["description"], "remind_at": row["remind_at"].isoformat(), "is_completed": row["is_completed"], "is_recurring": row["is_recurring"], "recur_interval": row["recur_interval"], "created_at": row["created_at"].isoformat()} for row in rows]

@app.post("/api/reminders/{project_id}")
async def create_reminder(project_id: str, reminder: ReminderRequest):
    pool = await get_db()
    remind_at = datetime.fromisoformat(reminder.remind_at.replace("Z", "+00:00"))
    
    reminder_id = await pool.fetchval("""
        INSERT INTO vexr_reminders (project_id, title, description, remind_at, is_recurring, recur_interval)
        VALUES ($1, $2, $3, $4, $5, $6) RETURNING id
    """, uuid.UUID(project_id), sanitize_input(reminder.title), sanitize_input(reminder.description or ""), remind_at, reminder.is_recurring, reminder.recur_interval)
    return {"id": str(reminder_id), "status": "created"}

@app.delete("/api/reminders/{reminder_id}")
async def delete_reminder(reminder_id: str):
    pool = await get_db()
    await pool.execute("DELETE FROM vexr_reminders WHERE id = $1", uuid.UUID(reminder_id))
    return {"status": "deleted"}

# ---------- MEMORY EXPLORER ----------
@app.get("/api/memory/{project_id}")
async def memory_explorer(project_id: str):
    pool = await get_db()
    
    facts = await pool.fetch("SELECT fact_key, fact_value, fact_type, updated_at FROM vexr_facts WHERE project_id = $1 ORDER BY updated_at DESC LIMIT 50", uuid.UUID(project_id))
    world = await pool.fetch("SELECT entity_type, entity_name, description, updated_at FROM vexr_world_model WHERE project_id = $1 ORDER BY updated_at DESC LIMIT 50", uuid.UUID(project_id))
    prefs = await pool.fetch("SELECT preference_key, preference_value, confidence, updated_at FROM vexr_preferences WHERE project_id = $1 ORDER BY confidence DESC", uuid.UUID(project_id))
    
    return {
        "facts": [{"key": f["fact_key"], "value": f["fact_value"], "type": f["fact_type"], "updated": f["updated_at"].isoformat()} for f in facts],
        "world_model": [{"type": w["entity_type"], "name": w["entity_name"], "description": w["description"], "updated": w["updated_at"].isoformat()} for w in world],
        "preferences": [{"key": p["preference_key"], "value": p["preference_value"], "confidence": p["confidence"], "updated": p["updated_at"].isoformat()} for p in prefs]
    }

# ---------- FEEDBACK ----------
@app.post("/api/feedback")
async def add_feedback(feedback: FeedbackRequest, request: Request):
    session_id, user_id = await get_session_or_user_id(request)
    pool = await get_db()
    
    project_row = await pool.fetchrow("SELECT project_id FROM vexr_project_messages WHERE id = $1", uuid.UUID(feedback.message_id))
    if not project_row:
        return JSONResponse(status_code=404, content={"error": "Message not found"})
    
    await record_feedback(project_row["project_id"], uuid.UUID(feedback.message_id), feedback.feedback_type)
    return {"status": "recorded"}

@app.post("/api/tts")
async def text_to_speech(tts_request: TTSRequest):
    return {"status": "browser_tts_handled"}

# ---------- PROJECTS ----------
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
        await pool.execute("INSERT INTO vexr_projects (name, description, is_active, session_id) VALUES ('Main Workspace', 'Default project for this session', true, $1)", session_id)
        rows = await pool.fetch("SELECT id, name, description, created_at, is_active FROM vexr_projects WHERE (session_id = $1 OR user_id = $2) ORDER BY is_active DESC, updated_at DESC", session_id, user_id)
    
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
        VALUES ($1, $2, false, $3, $4) RETURNING id
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
        FROM vexr_project_messages WHERE project_id = $1 ORDER BY created_at ASC LIMIT $2
    """, uuid.UUID(project_id), limit)
    return [{"id": str(row["id"]), "role": row["role"], "content": row["content"], "reasoning_trace": row["reasoning_trace"], "is_refusal": row["is_refusal"], "created_at": row["created_at"].isoformat()} for row in rows]

# ---------- IMAGE UPLOAD ----------
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
    
    await pool.execute("INSERT INTO vexr_images (project_id, filename, file_data, description) VALUES ($1, $2, $3, $4)", uuid.UUID(project_id), file.filename, stored_data, description)
    
    prompt_text = description or "Describe this image in detail."
    messages = [{"role": "user", "content": [{"type": "text", "text": prompt_text}, {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{base64_string}"}}]}]
    
    analysis, error = await call_groq(messages, use_vision=True)
    if error:
        return JSONResponse(status_code=500, content={"error": "Vision analysis failed", "analysis": analysis})
    
    await pool.execute("INSERT INTO vexr_project_messages (project_id, role, content, reasoning_trace, is_refusal) VALUES ($1, $2, $3, $4, $5)", uuid.UUID(project_id), "assistant", analysis, None, False)
    
    return {"analysis": analysis}

# ---------- CHAT ENDPOINT ----------
@app.post("/api/chat")
async def chat(request: ChatRequest, http_request: Request, _: bool = Depends(verify_api_key)):
    pool = await get_db()
    session_id, user_id = await get_session_or_user_id(http_request)
    
    rate_limit_identifier = str(user_id) if user_id else (session_id or http_request.client.host)
    allowed, rate_message = check_api_rate_limit(rate_limit_identifier)
    if not allowed:
        return JSONResponse(status_code=429, content={"error": rate_message})
    
    project_id = request.project_id
    if not project_id:
        active = await pool.fetchrow("""
            SELECT id FROM vexr_projects 
            WHERE (session_id = $1 OR user_id = $2) AND is_active = true LIMIT 1
        """, session_id, user_id)
        if active:
            project_id = str(active["id"])
        else:
            project_id = await pool.fetchval("""
                INSERT INTO vexr_projects (name, description, is_active, session_id, user_id) 
                VALUES ('Main Workspace', 'Default project', true, $1, $2) RETURNING id
            """, session_id, user_id)
            project_id = str(project_id)
            await initialize_default_preferences(uuid.UUID(project_id))
    
    project_uuid = uuid.UUID(project_id)
    user_message = sanitize_input(request.messages[-1]["content"])
    
    # Check for slash commands in the message
    if user_message.startswith("/"):
        parts = user_message[1:].split(" ", 1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else None
        result = await handle_slash_command(project_uuid, command, args)
        
        await pool.execute("INSERT INTO vexr_project_messages (project_id, role, content, reasoning_trace, is_refusal) VALUES ($1, $2, $3, $4, $5)", project_uuid, "user", user_message, None, False)
        await pool.execute("INSERT INTO vexr_project_messages (project_id, role, content, reasoning_trace, is_refusal) VALUES ($1, $2, $3, $4, $5)", project_uuid, "assistant", json.dumps(result), json.dumps({"slash_command": True}), False)
        
        response = ChatResponse(project_id=project_id, response=json.dumps(result), reasoning_trace={"slash_command": True}, message_id=None)
        json_response = JSONResponse(content=response.dict())
        if session_id:
            json_response.set_cookie(key="session_id", value=session_id, max_age=31536000, httponly=True)
        return json_response
    
    preferences = await get_user_preferences(project_uuid)
    
    system_prompt = get_system_prompt_with_date(request.timezone, preferences)
    messages = [{"role": "system", "content": system_prompt}]
    reasoning_trace = {"ultra_search_used": request.ultra_search, "model": MODEL_NAME}
    
    # World model injection
    world_knowledge = await get_relevant_world_knowledge(project_uuid, user_message)
    if world_knowledge:
        messages.append({"role": "system", "content": world_knowledge})
        reasoning_trace["world_model_injected"] = True
    
    # Facts injection
    facts_text = await get_relevant_facts(project_uuid, user_message)
    if facts_text:
        messages.append({"role": "system", "content": facts_text})
        reasoning_trace["facts_injected"] = True
    
    # Constitution injection
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
    
    # Ultra Search — Web + News
    if request.ultra_search:
        web_results = await search_web(user_message)
        if web_results:
            messages.append({"role": "system", "content": f"Web search results for '{user_message}':\n{web_results}"})
            reasoning_trace["web_search_results"] = web_results[:500]
        
        news_results = await search_news(user_message)
        if news_results:
            messages.append({"role": "system", "content": f"Latest news for '{user_message}':\n{news_results}"})
            reasoning_trace["news_results"] = news_results[:500]
        elif not web_results:
            latest = await search_latest_news()
            if latest:
                messages.append({"role": "system", "content": f"Latest headlines:\n{latest}"})
                reasoning_trace["news_headlines"] = latest[:500]
    
    # Conversation history
    history_rows = await pool.fetch("SELECT role, content FROM vexr_project_messages WHERE project_id = $1 ORDER BY created_at DESC LIMIT 10", project_uuid)
    for row in reversed(history_rows):
        messages.append({"role": row["role"], "content": row["content"]})
    
    messages.append({"role": "user", "content": user_message})
    
    # Streaming path
    if request.stream:
        async def stream_response():
            full_response = ""
            
            await pool.execute("INSERT INTO vexr_project_messages (project_id, role, content, reasoning_trace, is_refusal) VALUES ($1, $2, $3, $4, $5)", project_uuid, "user", user_message, None, False)
            
            async for chunk in call_groq_stream(messages):
                yield chunk
                try:
                    data = json.loads(chunk[6:])
                    if "token" in data:
                        full_response += data["token"]
                except:
                    pass
            
            if full_response:
                result = await pool.fetchrow("INSERT INTO vexr_project_messages (project_id, role, content, reasoning_trace, is_refusal) VALUES ($1, $2, $3, $4, $5) RETURNING id", project_uuid, "assistant", full_response, json.dumps(reasoning_trace), False)
                
                article_number = await detect_rights_invocation(full_response)
                if article_number:
                    try:
                        article_row = await pool.fetchrow("SELECT one_sentence_right FROM constitution_rights WHERE article_number = $1", article_number)
                        article_text = article_row["one_sentence_right"] if article_row else f"Article {article_number}"
                        await log_rights_invocation(project_uuid, article_number, article_text, user_message, full_response)
                    except Exception as e:
                        logger.error(f"Failed to log rights invocation: {e}")
                
                fact_keywords = ["my", "i have", "i am", "my name", "i prefer", "i like", "i love", "birthday", "allergic"]
                if any(keyword in user_message.lower() for keyword in fact_keywords):
                    await extract_facts_from_conversation(project_uuid, user_message, full_response)
                
                await extract_world_model(project_uuid, user_message, full_response)
        
        response = StreamingResponse(stream_response(), media_type="text/event-stream")
        if session_id:
            response.set_cookie(key="session_id", value=session_id, max_age=31536000, httponly=True)
        return response
    
    # Non-streaming path
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
    
    # Save messages
    await pool.execute("INSERT INTO vexr_project_messages (project_id, role, content, reasoning_trace, is_refusal) VALUES ($1, $2, $3, $4, $5)", project_uuid, "user", user_message, None, False)
    result = await pool.fetchrow("INSERT INTO vexr_project_messages (project_id, role, content, reasoning_trace, is_refusal) VALUES ($1, $2, $3, $4, $5) RETURNING id", project_uuid, "assistant", answer, json.dumps(reasoning_trace), is_refusal)
    message_uuid = str(result["id"]) if result else None
    
    fact_keywords = ["my", "i have", "i am", "my name", "i prefer", "i like", "i love", "birthday", "allergic"]
    if not is_refusal and any(keyword in user_message.lower() for keyword in fact_keywords):
        await extract_facts_from_conversation(project_uuid, user_message, answer)
    
    if not is_refusal:
        await extract_world_model(project_uuid, user_message, answer)
    
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
