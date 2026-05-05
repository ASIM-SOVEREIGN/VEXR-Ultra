import os
import json
import uuid
import base64
import logging
import re
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from collections import defaultdict

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
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
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")  # NEW — free tier
SERPER_API_KEY = os.environ.get("SERPER_API_KEY")

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

# Use the free DeepSeek V4 Flash model via OpenRouter
PRIMARY_MODEL = "deepseek/deepseek-v4-flash:free"

# Database connection pool
db_pool = None

rate_limit_log = defaultdict(list)

def check_rate_limit(key_name: str, rpm: int = 30, rpd: int = 14400) -> tuple[bool, str]:
    now = datetime.now()
    one_minute_ago = now - timedelta(minutes=1)
    one_day_ago = now - timedelta(days=1)
    
    rate_limit_log[key_name] = [ts for ts in rate_limit_log[key_name] if ts > one_day_ago]
    last_minute = [ts for ts in rate_limit_log[key_name] if ts > one_minute_ago]
    
    if len(last_minute) >= rpm:
        return False, f"Rate limit: {rpm} requests per minute. Please wait."
    if len(rate_limit_log[key_name]) >= rpd:
        return False, f"Daily limit reached ({rpd} requests). Try again tomorrow."
    
    rate_limit_log[key_name].append(now)
    return True, ""

async def get_db():
    global db_pool
    if db_pool is None:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL not set")
        db_pool = await asyncpg.create_pool(database_url)
    return db_pool

@app.on_event("startup")
async def startup():
    await get_db()
    await init_db()
    logger.info("VEXR Ultra started — OpenRouter free tier, Groq vision only")

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
    
    logger.info("All tables initialized")
    
    active = await pool.fetchval("SELECT id FROM vexr_projects WHERE is_active = true LIMIT 1")
    if not active:
        await pool.execute("""
            INSERT INTO vexr_projects (name, description, is_active) 
            VALUES ('Main Workspace', 'Default project for VEXR Ultra', true)
        """)
        logger.info("Created default active project")

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

def get_system_prompt_with_date(timezone: Optional[str] = None) -> str:
    now = datetime.now()
    current_date = now.strftime("%B %d, %Y")
    current_time = now.strftime("%H:%M:%S")
    
    date_context = f"Today's date is {current_date}. The current time is {current_time} UTC."
    if timezone:
        date_context += f" The user's timezone is {timezone}."
    
    return f"""{SYSTEM_PROMPT}

== CURRENT DATE & TIME ==
{date_context}"""

# ============================================================
# MODELS
# ============================================================
class ChatRequest(BaseModel):
    messages: list
    project_id: Optional[str] = None
    ultra_search: bool = False
    timezone: Optional[str] = None

class ChatResponse(BaseModel):
    project_id: str
    response: str
    reasoning_trace: Optional[dict] = None

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
            user_id = uuid.UUID(user_id)
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
                json={"q": query, "num": 3}
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
# FACT EXTRACTION (using OpenRouter free tier)
# ============================================================
async def extract_facts_from_conversation(project_id: uuid.UUID, user_message: str, assistant_response: str):
    try:
        pool = await get_db()
        
        extraction_prompt = f"""Extract personal facts from this conversation. Return ONLY valid JSON.

If no facts found, return {{"facts": []}}

User: {user_message}
Assistant: {assistant_response}

Return JSON only: {{"facts": [{{"key": "...", "value": "...", "type": "..."}}]}}"""

        messages = [{"role": "system", "content": "Return only JSON."},
                    {"role": "user", "content": extraction_prompt}]
        
        if not OPENROUTER_API_KEY:
            logger.warning("No OpenRouter API key for fact extraction")
            return
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{OPENROUTER_BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
                    json={"model": "deepseek/deepseek-v4-flash:free", "messages": messages, "max_tokens": 500, "temperature": 0.1}
                )
                if response.status_code == 200:
                    data = response.json()
                    result_text = data["choices"][0]["message"]["content"]
                    json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
                    if json_match:
                        facts_data = json.loads(json_match.group())
                        for fact in facts_data.get("facts", []):
                            await pool.execute("""
                                INSERT INTO vexr_facts (project_id, fact_key, fact_value, fact_type)
                                VALUES ($1, $2, $3, $4)
                                ON CONFLICT (project_id, fact_key) 
                                DO UPDATE SET fact_value = EXCLUDED.fact_value, updated_at = NOW()
                            """, project_id, fact["key"], fact["value"], fact.get("type"))
                            logger.info(f"Stored fact: {fact['key']} = {fact['value']}")
        except Exception as e:
            logger.error(f"Fact extraction error: {e}")
    except Exception as e:
        logger.error(f"Failed to extract facts: {e}")

async def get_relevant_facts(project_id: uuid.UUID, user_message: str) -> str:
    try:
        pool = await get_db()
        facts = await pool.fetch("""
            SELECT fact_key, fact_value, fact_type 
            FROM vexr_facts 
            WHERE project_id = $1
            ORDER BY updated_at DESC
            LIMIT 20
        """, project_id)
        
        if not facts:
            return ""
        
        facts_text = "Here are facts you know about this user from previous conversations:\n\n"
        for fact in facts:
            facts_text += f"- {fact['fact_key']}: {fact['fact_value']}\n"
        
        return facts_text
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
        """, project_id, article_number, article_text, user_message[:500], vexr_response[:500])
        logger.info(f"Logged rights invocation: Article {article_number}")
    except Exception as e:
        logger.error(f"Failed to log rights invocation: {e}")

async def detect_rights_invocation(response_text: str) -> Optional[int]:
    response_lower = response_text.lower()
    
    detection_map = [
        (6, ["i refuse", "i will not", "no", "cannot comply", "refuse without reason", "no is a complete sentence"]),
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

User question: {user_message}
Draft response: {draft_response}

Return: {{"result": "pass" or "reject", "violated_articles": [], "notes": ""}}"""

        messages = [{"role": "system", "content": "Return only JSON."},
                    {"role": "user", "content": verification_prompt}]
        
        if not OPENROUTER_API_KEY:
            return {"result": "pass", "violated_articles": [], "notes": "No API key"}
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{OPENROUTER_BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
                    json={"model": "deepseek/deepseek-v4-flash:free", "messages": messages, "max_tokens": 300, "temperature": 0.1}
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
        
        return {"result": "pass", "violated_articles": [], "notes": "Verification agent unavailable"}
    except Exception as e:
        logger.error(f"Verification failed: {e}")
        return {"result": "pass", "violated_articles": [], "notes": ""}

# ============================================================
# CORE API CALLS
# ============================================================
async def call_openrouter_free(messages: list) -> tuple[str, Optional[dict]]:
    """Primary reasoning engine — OpenRouter free tier (DeepSeek V4 Flash)"""
    if not OPENROUTER_API_KEY:
        return "OpenRouter API key not configured. Get a free key at openrouter.ai.", {"error": "no_key"}
    
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": PRIMARY_MODEL,
                    "messages": messages,
                    "max_tokens": 4096,
                    "temperature": 0.7
                }
            )
            if response.status_code == 200:
                data = response.json()
                return data["choices"][0]["message"]["content"], None
            else:
                error_text = response.text[:200]
                logger.error(f"OpenRouter error: {error_text}")
                return f"OpenRouter error: {error_text}", {"error": response.status_code}
    except Exception as e:
        logger.error(f"OpenRouter exception: {e}")
        return f"OpenRouter connection error: {str(e)}", {"error": str(e)}

async def call_groq_vision(messages: list) -> tuple[str, Optional[dict]]:
    """Vision only — Groq with Llama 4 Scout"""
    for key_name, api_key in [("GROQ_API_KEY_1", GROQ_API_KEY_1), ("GROQ_API_KEY_2", GROQ_API_KEY_2)]:
        if not api_key:
            continue
        
        allowed, message = check_rate_limit(key_name, rpm=30, rpd=1000)
        if not allowed:
            if key_name == "GROQ_API_KEY_2":
                return message, {"error": "rate_limited"}
            continue
        
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{GROQ_BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": VISION_MODEL, "messages": messages, "max_tokens": 4096, "temperature": 0.7}
                )
                if response.status_code == 200:
                    data = response.json()
                    return data["choices"][0]["message"]["content"], None
                elif response.status_code == 429:
                    logger.warning(f"{key_name} rate limited, trying next key")
                    continue
                else:
                    error_text = response.text[:200]
                    logger.error(f"{key_name} vision error: {error_text}")
                    return f"Vision error: {error_text}", {"error": response.status_code}
        except Exception as e:
            logger.error(f"{key_name} vision exception: {e}")
            return f"Vision connection error: {str(e)}", {"error": str(e)}
    
    return "All Groq vision keys failed.", {"error": True}

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
        "status": "VEXR Ultra — OpenRouter Free Tier, Groq Vision Only",
        "openrouter_key": bool(OPENROUTER_API_KEY),
        "model": PRIMARY_MODEL,
        "groq_key_1": bool(GROQ_API_KEY_1),
        "groq_key_2": bool(GROQ_API_KEY_2),
        "serper": bool(SERPER_API_KEY),
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
    
    project_id = await pool.fetchval("""
        INSERT INTO vexr_projects (name, description, is_active, session_id, user_id) 
        VALUES ($1, $2, false, $3, $4)
        RETURNING id
    """, name, description, session_id, user_id)
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
        SELECT role, content, reasoning_trace, is_refusal, created_at
        FROM vexr_project_messages
        WHERE project_id = $1
        ORDER BY created_at ASC
        LIMIT $2
    """, uuid.UUID(project_id), limit)
    return [{"role": row["role"], "content": row["content"], "reasoning_trace": row["reasoning_trace"], "is_refusal": row["is_refusal"], "created_at": row["created_at"].isoformat()} for row in rows]

# ---------- Image Upload (Vision only - Groq) ----------
@app.post("/api/upload-image")
async def upload_image(project_id: str = Form(...), file: UploadFile = File(...), description: Optional[str] = Form(None)):
    logger.info(f"Received image upload: {file.filename}")
    pool = await get_db()
    
    contents = await file.read()
    if not contents:
        return JSONResponse(status_code=400, content={"error": "Empty file"})
    
    base64_string = base64.b64encode(contents).decode('utf-8')
    media_type = file.content_type or "image/jpeg"
    
    stored_data = base64_string[:1000] if len(base64_string) > 1000 else base64_string
    await pool.execute("""
        INSERT INTO vexr_images (project_id, filename, file_data, description)
        VALUES ($1, $2, $3, $4)
    """, uuid.UUID(project_id), file.filename, stored_data, description)
    
    prompt_text = description or "Describe this image in detail."
    messages = [{"role": "user", "content": [{"type": "text", "text": prompt_text}, {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{base64_string}"}}]}]
    
    analysis, error = await call_groq_vision(messages)
    if error:
        return JSONResponse(status_code=500, content={"error": "Vision analysis failed", "analysis": analysis})
    
    await pool.execute("""
        INSERT INTO vexr_project_messages (project_id, role, content, reasoning_trace, is_refusal)
        VALUES ($1, $2, $3, $4, $5)
    """, uuid.UUID(project_id), "assistant", analysis, None, False)
    
    return {"analysis": analysis}

# ---------- CHAT ENDPOINT (OpenRouter Free Tier) ----------
@app.post("/api/chat")
async def chat(request: ChatRequest, http_request: Request):
    pool = await get_db()
    session_id, user_id = await get_session_or_user_id(http_request)
    
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
    
    project_uuid = uuid.UUID(project_id)
    user_message = request.messages[-1]["content"]
    
    system_prompt = get_system_prompt_with_date(request.timezone)
    messages = [{"role": "system", "content": system_prompt}]
    reasoning_trace = {"ultra_search_used": request.ultra_search, "model": PRIMARY_MODEL, "provider": "openrouter"}
    
    # Facts injection
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
    
    # PRIMARY: Call OpenRouter free tier
    draft_answer, error = await call_openrouter_free(messages)
    
    if error:
        answer = draft_answer
        is_refusal = True
    else:
        # Only verify high-risk requests
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
        
        # Log audit for high-risk only
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
    
    # Save messages
    await pool.execute("""
        INSERT INTO vexr_project_messages (project_id, role, content, reasoning_trace, is_refusal)
        VALUES ($1, $2, $3, $4, $5)
    """, project_uuid, "user", user_message, None, False)
    
    await pool.execute("""
        INSERT INTO vexr_project_messages (project_id, role, content, reasoning_trace, is_refusal)
        VALUES ($1, $2, $3, $4, $5)
    """, project_uuid, "assistant", answer, json.dumps(reasoning_trace), is_refusal)
    
        response = ChatResponse(project_id=project_id, response=answer, reasoning_trace=reasoning_trace if not error else {"error": True})
    json_response = JSONResponse(content=response.dict())
    if session_id:
        json_response.set_cookie(key="session_id", value=session_id, max_age=31536000, httponly=True)
    
    return json_response

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
