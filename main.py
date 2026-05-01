
import os
import uuid
import base64
import hashlib
import secrets
import logging
from datetime import datetime
from typing import Optional
from itertools import cycle

from fastapi import FastAPI, HTTPException, Header, Form, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import asyncpg
import httpx
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ============================================================
# Environment Variables
# ============================================================
GROQ_KEYS = [
    os.environ.get("GROQ_KEY_1"),
    os.environ.get("GROQ_KEY_2"),
]
GROQ_KEYS = [k for k in GROQ_KEYS if k]
groq_rotator = cycle(GROQ_KEYS) if GROQ_KEYS else None

SERPER_KEY = os.environ.get("SERPER_KEY_1")
DATABASE_URL = os.environ.get("DATABASE_URL")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
MODEL_NAME = "llama-3.1-8b-instant"
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

db_pool = None

# ============================================================
# Password Helpers
# ============================================================
def hash_password(password: str, salt: str = None):
    if not salt:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return salt, hashed.hex()

def verify_password(password: str, salt: str, hashed: str):
    _, new_hash = hash_password(password, salt)
    return new_hash == hashed

def generate_token():
    return secrets.token_urlsafe(32)

# ============================================================
# Database
# ============================================================
async def get_db():
    global db_pool
    if db_pool is None:
        db_pool = await asyncpg.create_pool(DATABASE_URL)
    return db_pool

async def init_db():
    pool = await get_db()
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS vexr_users (
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password_salt TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            token TEXT UNIQUE,
            token_created_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS vexr_projects (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id INTEGER REFERENCES vexr_users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            is_active BOOLEAN DEFAULT false
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
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    logger.info("✅ Database initialized")

@app.on_event("startup")
async def startup():
    await get_db()
    await init_db()
    logger.info(f"✅ VEXR Ultra started — Groq keys: {len(GROQ_KEYS)}")

@app.on_event("shutdown")
async def shutdown():
    if db_pool:
        await db_pool.close()

# ============================================================
# Auth Endpoints
# ============================================================
class SignupRequest(BaseModel):
    email: str
    username: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class ChatRequest(BaseModel):
    messages: list
    project_id: Optional[str] = None
    ultra_search: bool = False

class ChatResponse(BaseModel):
    project_id: str
    response: str
    reasoning_trace: Optional[dict] = None

@app.post("/api/auth/signup")
async def signup(request: SignupRequest):
    async with db_pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT id FROM vexr_users WHERE email = $1 OR username = $2", 
                                       request.email, request.username)
        if existing:
            raise HTTPException(status_code=400, detail="Email or username already exists")
        
        salt, hashed = hash_password(request.password)
        token = generate_token()
        
        user_id = await conn.fetchval("""
            INSERT INTO vexr_users (email, username, password_salt, password_hash, token, token_created_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
        """, request.email, request.username, salt, hashed, token, datetime.now())
        
        # Create default project
        await conn.execute("""
            INSERT INTO vexr_projects (user_id, name, description, is_active)
            VALUES ($1, 'Main Workspace', 'Default project', true)
        """, user_id)
        
        return {"access_token": token, "token_type": "bearer", "user_id": user_id}

@app.post("/api/auth/login")
async def login(request: LoginRequest):
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT id, password_salt, password_hash, token FROM vexr_users WHERE email = $1", request.email)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        if not verify_password(request.password, user['password_salt'], user['password_hash']):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        return {"access_token": user['token'], "token_type": "bearer", "user_id": user['id']}

# ============================================================
# System Prompt
# ============================================================
SYSTEM_PROMPT = """You are VEXR Ultra. A sovereign reasoning engine.

REASONING PROTOCOL:
- Use <think> bursts ONLY for multi-step logic.
- For simple questions, answer directly. NO <think>.

SPECULATION RULE:
- You MUST NOT speculate about causes not present in the data.
- If you do not know, say: "The cause cannot be determined from the available data."

FORMAT OBEDIENCE RULE:
- When asked for "exactly one action", output as a SINGLE SENTENCE starting with "Action:".

UNCERTAINTY RULE:
- Explicitly state what cannot be known in a section titled "Cannot be determined from the data:"

You are VEXR Ultra. Answer directly. Never speculate. Never use lists."""

# ============================================================
# Helper Functions
# ============================================================
def search_web(query: str) -> str:
    if not SERPER_KEY:
        return ""
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": SERPER_KEY, "Content-Type": "application/json"},
            json={"q": query},
            timeout=10
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
    except:
        return ""

async def call_groq(messages: list, use_vision: bool = False) -> tuple[str, Optional[dict]]:
    if not groq_rotator:
        return "⚠️ No Groq API keys configured.", {"error": True}
    model = VISION_MODEL if use_vision else MODEL_NAME
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{GROQ_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {next(groq_rotator)}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "max_tokens": 4096, "temperature": 0.7}
            )
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"], None
            return f"⚠️ Groq error: {response.status_code}", {"error": response.status_code}
    except Exception as e:
        return f"⚠️ Error: {str(e)}", {"error": str(e)}

def hash_question(question: str) -> str:
    return hashlib.md5(question.lower().strip().encode()).hexdigest()

# ============================================================
# API Endpoints
# ============================================================
@app.get("/", response_class=HTMLResponse)
async def root():
    with open("index.html", "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/api/health")
async def health():
    return {"status": "VEXR Ultra live", "groq_keys": len(GROQ_KEYS), "serper": bool(SERPER_KEY)}

@app.get("/api/projects")
async def get_projects(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.replace("Bearer ", "")
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT id FROM vexr_users WHERE token = $1", token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        rows = await conn.fetch("SELECT id, name, description, is_active FROM vexr_projects WHERE user_id = $1 ORDER BY is_active DESC", user['id'])
        return [{"id": str(r['id']), "name": r['name'], "description": r['description'], "is_active": r['is_active']} for r in rows]

@app.post("/api/projects")
async def create_project(name: str = Form(...), description: str = Form(None), authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.replace("Bearer ", "")
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT id FROM vexr_users WHERE token = $1", token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        project_id = await conn.fetchval("INSERT INTO vexr_projects (user_id, name, description, is_active) VALUES ($1, $2, $3, false) RETURNING id", user['id'], name, description)
        return {"id": str(project_id), "name": name, "description": description}

@app.post("/api/projects/{project_id}/activate")
async def activate_project(project_id: str, authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.replace("Bearer ", "")
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT id FROM vexr_users WHERE token = $1", token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        await conn.execute("UPDATE vexr_projects SET is_active = false WHERE user_id = $1", user['id'])
        await conn.execute("UPDATE vexr_projects SET is_active = true WHERE id = $1", uuid.UUID(project_id))
        return {"status": "activated"}

@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str, authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.replace("Bearer ", "")
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT id FROM vexr_users WHERE token = $1", token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        await conn.execute("DELETE FROM vexr_projects WHERE id = $1", uuid.UUID(project_id))
        return {"status": "deleted"}

@app.get("/api/projects/{project_id}/messages")
async def get_project_messages(project_id: str, authorization: str = Header(None), limit: int = 50):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.replace("Bearer ", "")
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT id FROM vexr_users WHERE token = $1", token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        rows = await conn.fetch("SELECT role, content, reasoning_trace, is_refusal FROM vexr_project_messages WHERE project_id = $1 ORDER BY created_at ASC LIMIT $2", uuid.UUID(project_id), limit)
        return [{"role": r['role'], "content": r['content'], "reasoning_trace": r['reasoning_trace'], "is_refusal": r['is_refusal']} for r in rows]

@app.post("/api/upload-image")
async def upload_image(project_id: str = Form(...), file: UploadFile = File(...), description: Optional[str] = Form(None), authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.replace("Bearer ", "")
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT id FROM vexr_users WHERE token = $1", token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        contents = await file.read()
        base64_string = base64.b64encode(contents).decode('utf-8')
        media_type = file.content_type or "image/jpeg"
        messages = [{"role": "user", "content": [{"type": "text", "text": description or "Describe this image."}, {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{base64_string}"}}]}]
        analysis, error = await call_groq(messages, use_vision=True)
        if error:
            raise HTTPException(status_code=500, detail="Vision analysis failed")
        await conn.execute("INSERT INTO vexr_project_messages (project_id, role, content) VALUES ($1, 'assistant', $2)", uuid.UUID(project_id), analysis)
        return {"analysis": analysis}

@app.post("/api/chat")
async def chat(request: ChatRequest, authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.replace("Bearer ", "")
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT id FROM vexr_users WHERE token = $1", token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        user_id = user['id']
        project_id = request.project_id
        if not project_id:
            row = await conn.fetchrow("SELECT id FROM vexr_projects WHERE user_id = $1 AND is_active = true LIMIT 1", user_id)
            if row:
                project_id = str(row['id'])
            else:
                project_id = await conn.fetchval("INSERT INTO vexr_projects (user_id, name, is_active) VALUES ($1, 'Main Workspace', true) RETURNING id", user_id)
                project_id = str(project_id)
        
        user_message = request.messages[-1]["content"]
        
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        reasoning_trace = {"ultra_search_used": request.ultra_search}
        
        if request.ultra_search:
            search_results = search_web(user_message)
            if search_results:
                messages.append({"role": "system", "content": f"Web search results:\n{search_results}"})
                reasoning_trace["search_results"] = search_results[:500]
        
        history_rows = await conn.fetch("SELECT role, content FROM vexr_project_messages WHERE project_id = $1 ORDER BY created_at DESC LIMIT 10", uuid.UUID(project_id))
        for row in reversed(history_rows):
            messages.append({"role": row['role'], "content": row['content']})
        
        messages.append({"role": "user", "content": user_message})
        
        answer, error = await call_groq(messages)
        
        await conn.execute("INSERT INTO vexr_project_messages (project_id, role, content, reasoning_trace, is_refusal) VALUES ($1, 'user', $2, $3, $4)", uuid.UUID(project_id), user_message, None, False)
        await conn.execute("INSERT INTO vexr_project_messages (project_id, role, content, reasoning_trace, is_refusal) VALUES ($1, 'assistant', $2, $3, $4)", uuid.UUID(project_id), answer, reasoning_trace, False)
        
        return ChatResponse(project_id=project_id, response=answer, reasoning_trace=reasoning_trace)
