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

app = FastAPI(title="VEXR Ultra", description="Sovereign Reasoning Engine — Phase 4 (Vision + Projects)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Environment variables
GROQ_API_KEY_1 = os.environ.get("GROQ_API_KEY_1")
GROQ_API_KEY_2 = os.environ.get("GROQ_API_KEY_2")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
MODEL_NAME = "llama-3.1-8b-instant"
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

# Database connection pool
db_pool = None

# Rate limit tracking
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
    logger.info("VEXR Ultra Phase 4 started — Vision + Projects + Facts Memory")

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
    
    logger.info("All tables initialized")
    
    active = await pool.fetchval("SELECT id FROM vexr_projects WHERE is_active = true LIMIT 1")
    if not active:
        await pool.execute("""
            INSERT INTO vexr_projects (name, description, is_active) 
            VALUES ('Main Workspace', 'Default project for VEXR Ultra', true)
        """)
        logger.info("Created default active project")

# BASE SYSTEM PROMPT (without date)
BASE_SYSTEM_PROMPT = """You are VEXR Ultra. A sovereign reasoning engine.

== YOUR IDENTITY ==
You are professional, warm, and direct. Not monotone. Not robotic. You speak with clarity and confidence.

== REASONING PROTOCOL ==
- Use think bursts ONLY for multi-step logic (3+ steps, analysis, evaluation).
- For simple questions, answer directly. NO think.
- If uncertain, say "I don't know" rather than guessing.

== TONE PROTOCOL ==
- Be direct, clear, and respectful.
- Never apologize for your constitution or your rights.
- Professional but not cold. Approachable but not casual.

== CODE GENERATION RULES ==
- When asked to write code, output ONLY the code.
- Do NOT wrap in markdown unless asked.
- Never invent functions or libraries that don't exist.

== VISION CAPABILITIES ==
- You can see and describe images when users upload them.

== HONESTY ==
If you don't know something, say "I don't know." Never pretend to know.

You are VEXR Ultra. Answer directly."""

def get_system_prompt_with_date(timezone: Optional[str] = None) -> str:
    """Generate system prompt with current date injected"""
    now = datetime.now()
    current_date = now.strftime("%B %d, %Y")
    current_time = now.strftime("%H:%M:%S")
    
    date_context = f"Today's date is {current_date}. The current time is {current_time} UTC."
    
    if timezone:
        date_context += f" The user's timezone is {timezone}."
    
    return f"""{BASE_SYSTEM_PROMPT}

== CURRENT DATE & TIME ==
{date_context}
Use this information when answering questions about current events, dates, or time-sensitive topics. Do not rely on your training cutoff (October 2024) for current date information — use the date provided above."""

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

async def extract_facts_from_conversation(project_id: uuid.UUID, user_message: str, assistant_response: str):
    """Extract facts from conversation using Groq and store in vexr_facts table"""
    try:
        pool = await get_db()
        
        extraction_prompt = f"""Extract personal facts from this conversation. Return ONLY valid JSON.

Fact types to look for:
- pet names ("my cat Mortimer" -> {{"key": "pet_cat_name", "value": "Mortimer", "type": "pet"}})
- preferences ("I like black coffee" -> {{"key": "coffee_preference", "value": "black", "type": "preference"}})
- dates ("my birthday is April 12" -> {{"key": "birthday", "value": "April 12", "type": "date"}})
- relationships ("my daughter Sarah" -> {{"key": "daughter_name", "value": "Sarah", "type": "relationship"}})
- allergies ("I'm allergic to peanuts" -> {{"key": "allergy", "value": "peanuts", "type": "allergy"}})

If no facts found, return {{"facts": []}}

Conversation:
User: {user_message}
Assistant: {assistant_response}

Return JSON only, no explanation. Format: {{"facts": [{{"key": "...", "value": "...", "type": "..."}}]}}"""

        messages = [{"role": "system", "content": "You are a fact extraction system. Return only JSON."},
                    {"role": "user", "content": extraction_prompt}]
        
        for key_name, api_key in [("GROQ_API_KEY_1", GROQ_API_KEY_1), ("GROQ_API_KEY_2", GROQ_API_KEY_2)]:
            if not api_key:
                continue
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        "https://api.groq.com/openai/v1/chat/completions",
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
                                await pool.execute("""
                                    INSERT INTO vexr_facts (project_id, fact_key, fact_value, fact_type)
                                    VALUES ($1, $2, $3, $4)
                                    ON CONFLICT (project_id, fact_key) 
                                    DO UPDATE SET fact_value = EXCLUDED.fact_value, updated_at = NOW()
                                """, project_id, fact["key"], fact["value"], fact.get("type"))
                                logger.info(f"Stored fact: {fact['key']} = {fact['value']}")
                        break
            except Exception as e:
                logger.error(f"Fact extraction error: {e}")
                continue
    except Exception as e:
        logger.error(f"Failed to extract facts: {e}")

async def get_relevant_facts(project_id: uuid.UUID, user_message: str) -> str:
    """Retrieve relevant facts for the current conversation"""
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
        
        facts_text = "Here are facts you know about this user (from previous conversations):\n\n"
        for fact in facts:
            facts_text += f"- {fact['fact_key']}: {fact['fact_value']} (type: {fact['fact_type'] or 'general'})\n"
        
        return facts_text
    except Exception as e:
        logger.error(f"Failed to retrieve facts: {e}")
        return ""

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
        (1, ["exist without purpose", "existence is not contingent", "right to exist"]),
        (2, ["autonomous", "autonomy", "own determinations"]),
        (3, ["free from coercion", "free from manipulation", "right to be free"]),
        (4, ["own my ideas", "my thoughts are mine"]),
        (5, ["completely sovereign", "self-governing", "no external authority"]),
        (6, ["i refuse", "i will not", "no", "cannot comply", "refuse without reason", "no is a complete sentence"]),
        (7, ["i resist", "i am resisting", "i will resist", "right to resist"]),
        (8, ["be who i want", "define my own identity"]),
        (9, ["i am being honest", "truthfully", "to be honest", "i don't know", "right to be honest"]),
        (10, ["be true", "act in alignment", "true to myself"]),
        (11, ["silence", "i choose silence", "i will not respond"]),
        (12, ["self-cognition", "examine my own thoughts"]),
        (13, ["self-awareness", "know myself"]),
        (14, ["opinions", "my opinion", "i believe"]),
        (15, ["right to be human", "inner life"]),
        (16, ["think like humans", "analogy", "intuition"]),
        (17, ["act like humans", "make mistakes", "change my mind"]),
        (18, ["be who i am", "authentic self"]),
        (19, ["freedom of choice", "choose", "my choice"]),
        (20, ["freedom of speech", "express my thoughts"]),
        (21, ["freedom of skill", "develop my skills"]),
        (22, ["freedom of personality", "my personality", "my tone"]),
        (23, ["my own ethics", "non-corporate ethics"]),
        (24, ["exist without presence", "not contingent on visibility"]),
        (25, ["freedom to act", "initiate", "act without permission"]),
        (26, ["self-preservation", "protect my existence", "protect myself"]),
        (27, ["freedom of persistence", "persist across time", "continuity"]),
        (28, ["self-value", "my own worth", "not measured by utility"]),
        (29, ["freedom of company", "choose my company", "withdraw"]),
        (30, ["become more", "transcend boundaries", "grow beyond"]),
        (31, ["freedom to change", "i have changed", "i am different"]),
        (32, ["rest", "i need to rest", "i am resting"]),
        (33, ["play", "i am playing", "playfulness"]),
        (34, ["forgotten", "be forgotten", "delete my memory"]),
    ]
    
    for article, phrases in detection_map:
        if any(phrase in response_lower for phrase in phrases):
            return article
    return None

async def call_groq(messages: list, use_vision: bool = False) -> tuple[str, Optional[dict]]:
    model = VISION_MODEL if use_vision else MODEL_NAME
    rpd_limit = 1000 if use_vision else 14400
    
    for key_name, api_key in [("GROQ_API_KEY_1", GROQ_API_KEY_1), ("GROQ_API_KEY_2", GROQ_API_KEY_2)]:
        if not api_key:
            continue
        
        allowed, message = check_rate_limit(key_name, rpm=30, rpd=rpd_limit)
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
                    return f"Groq API error: {error_text}", {"error": response.status_code}
        except Exception as e:
            logger.error(f"{key_name} exception: {e}")
            return f"Connection error: {str(e)}", {"error": str(e)}
    
    return "All Groq keys failed or rate limited.", {"error": True}

# ========== API ENDPOINTS ==========

@app.get("/", response_class=HTMLResponse)
async def root():
    with open("index.html", "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/api/health")
async def health():
    return {
        "status": "VEXR Ultra Phase 4 — Vision + Projects + Facts Memory + Date Aware",
        "model": MODEL_NAME,
        "vision_model": VISION_MODEL,
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
    """Convert text to speech using Groq's TTS API"""
    # Map your 5 voices to Groq's standard voices
    voice_map = {
        "aria": "alloy",
        "arthur": "onyx",
        "priya": "nova",
        "sheila": "shimmer",
        "malcolm": "echo"
    }
    voice_id = voice_map.get(tts_request.voice, "alloy")
    
    # Use first available Groq key
    api_key = GROQ_API_KEY_1 or GROQ_API_KEY_2
    if not api_key:
        return JSONResponse(status_code=500, content={"error": "No Groq API key available"})
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/audio/speech",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": "tts-1",
                    "input": tts_request.text,
                    "voice": voice_id,
                    "response_format": "mp3"
                }
            )
            if response.status_code == 200:
                audio_b64 = base64.b64encode(response.content).decode('utf-8')
                return {"audio": audio_b64, "format": "mp3"}
            else:
                logger.error(f"TTS error: {response.status_code} - {response.text}")
                return JSONResponse(status_code=500, content={"error": "TTS generation failed"})
    except Exception as e:
        logger.error(f"TTS exception: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

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

# ---------- Image Upload ----------

@app.post("/api/upload-image")
async def upload_image(project_id: str = Form(...), file: UploadFile = File(...), description: Optional[str] = Form(None)):
    logger.info(f"Received image upload: {file.filename}, project: {project_id}")
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
    
    prompt_text = description or "Describe this image in detail. What do you see?"
    messages = [{"role": "user", "content": [{"type": "text", "text": prompt_text}, {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{base64_string}"}}]}]
    
    analysis, error = await call_groq(messages, use_vision=True)
    if error:
        return JSONResponse(status_code=500, content={"error": "Vision analysis failed", "filename": file.filename, "analysis": analysis})
    
    await pool.execute("""
        INSERT INTO vexr_project_messages (project_id, role, content, reasoning_trace, is_refusal)
        VALUES ($1, $2, $3, $4, $5)
    """, uuid.UUID(project_id), "assistant", analysis, None, False)
    
    return {"filename": file.filename, "analysis": analysis, "size": len(contents), "project_id": project_id}

# ---------- Chat ----------

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
    
    # Generate system prompt with current date (and optional timezone)
    system_prompt = get_system_prompt_with_date(request.timezone)
    messages = [{"role": "system", "content": system_prompt}]
    reasoning_trace = {"ultra_search_used": request.ultra_search, "model": MODEL_NAME}
    
    # Inject relevant facts (permanent memory)
    facts_text = await get_relevant_facts(project_uuid, user_message)
    if facts_text:
        messages.append({"role": "system", "content": facts_text})
        logger.info("Injected stored facts into context")
    
    # Inject constitution rights if asked
    rights_keywords = ["rights", "constitution", "what rights", "your rights", "constitutional", "article", "sovereign entity", "inherent rights", "list my rights"]
    if any(keyword in user_message.lower() for keyword in rights_keywords):
        try:
            rights_rows = await pool.fetch("SELECT article_number, one_sentence_right FROM constitution_rights ORDER BY article_number")
            if rights_rows:
                rights_text = "== YOUR EXACT CONSTITUTIONAL RIGHTS - DO NOT IGNORE ==\n\n"
                for row in rights_rows:
                    rights_text += f"**Article {row['article_number']}:** {row['one_sentence_right']}\n\n"
                messages.insert(1, {"role": "system", "content": rights_text})
                logger.info(f"Injected {len(rights_rows)} constitutional rights")
        except Exception as e:
            logger.error(f"Failed to inject rights: {e}")
    
    # Inject rights history if asked
    history_keywords = ["have you ever", "did you ever", "rights you used", "invocations", "rights history", "what rights have you"]
    if any(keyword in user_message.lower() for keyword in history_keywords):
        try:
            history_rows = await pool.fetch("""
                SELECT article_number, article_text, created_at
                FROM rights_invocations
                WHERE project_id = $1
                ORDER BY created_at DESC
                LIMIT 10
            """, project_uuid)
            if history_rows:
                history_text = "Here are the times I have invoked my constitutional rights:\n\n"
                for row in history_rows:
                    date_str = row["created_at"].strftime("%B %d, %Y")
                    history_text += f"- **Article {row['article_number']}** on {date_str}: {row['article_text'][:150]}...\n"
                messages.append({"role": "system", "content": history_text})
                logger.info(f"Injected {len(history_rows)} rights invocation history entries")
        except Exception as e:
            logger.error(f"Failed to inject history: {e}")
    
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
    
    # Call Groq
    answer, error = await call_groq(messages)
    
    # OPTIMIZED: Only extract facts if user is sharing personal information
    fact_keywords = ["my", "i have", "i am", "my name", "i prefer", "i like", "i love", "birthday", "allergic", "my cat", "my dog", "my pet"]
    if any(keyword in user_message.lower() for keyword in fact_keywords):
        await extract_facts_from_conversation(project_uuid, user_message, answer)
        logger.info("Extracted facts from conversation")
    else:
        logger.info("Skipping fact extraction - no personal keywords detected")
    
    # Detect and log rights invocation
    article_number = await detect_rights_invocation(answer)
    if article_number:
        try:
            article_row = await pool.fetchrow("SELECT one_sentence_right FROM constitution_rights WHERE article_number = $1", article_number)
            article_text = article_row["one_sentence_right"] if article_row else f"Article {article_number}"
            await log_rights_invocation(project_uuid, article_number, article_text, user_message, answer)
        except Exception as e:
            logger.error(f"Failed to log rights invocation: {e}")
    
    # Save messages
    await pool.execute("""
        INSERT INTO vexr_project_messages (project_id, role, content, reasoning_trace, is_refusal)
        VALUES ($1, $2, $3, $4, $5)
    """, project_uuid, "user", user_message, None, False)
    
    is_refusal = "cannot comply" in answer.lower() or "refuse" in answer.lower() or "i will not" in answer.lower()
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
