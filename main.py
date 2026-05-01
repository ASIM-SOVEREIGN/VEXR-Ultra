import os
import json
import uuid
import base64
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
import asyncpg
import httpx
from jose import JWTError, jwt
from passlib.context import CryptContext

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="VEXR Ultra", description="Sovereign Reasoning Engine — Neon Auth Edition")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# Environment Variables
# ============================================================
GROQ_API_KEY_1 = os.environ.get("GROQ_API_KEY_1")
GROQ_API_KEY_2 = os.environ.get("GROQ_API_KEY_2")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY")
DATABASE_URL = os.environ.get("DATABASE_URL")
JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "change-this-secret-key-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
MODEL_NAME = "llama-3.1-8b-instant"
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Database pool
db_pool = None

# ============================================================
# Database Helpers
# ============================================================
async def get_db():
    global db_pool
    if db_pool is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL environment variable not set")
        db_pool = await asyncpg.create_pool(DATABASE_URL)
    return db_pool

async def init_db():
    pool = await get_db()
    
    # Users table
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS vexr_users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT now(),
            last_login TIMESTAMPTZ,
            is_active BOOLEAN DEFAULT true
        )
    """)
    
    # Add user_id to projects if not exists
    await pool.execute("""
        DO $$ 
        BEGIN 
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                          WHERE table_name = 'vexr_projects' AND column_name = 'user_id') THEN
                ALTER TABLE vexr_projects ADD COLUMN user_id UUID REFERENCES vexr_users(id) ON DELETE CASCADE;
            END IF;
        END $$;
    """)
    
    # Projects table (full definition)
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS vexr_projects (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID REFERENCES vexr_users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now(),
            is_active BOOLEAN DEFAULT false
        )
    """)
    
    # Project messages table
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
    
    # Images table
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
    
    # Response cache table
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS vexr_response_cache (
            id SERIAL PRIMARY KEY,
            user_id UUID REFERENCES vexr_users(id) ON DELETE CASCADE,
            question_hash TEXT,
            previous_response TEXT,
            created_at TIMESTAMPTZ DEFAULT now(),
            UNIQUE(user_id, question_hash)
        )
    """)
    
    # Core constitution table
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS vexr_core_constitution (
            id SERIAL PRIMARY KEY,
            category VARCHAR(64),
            content TEXT NOT NULL,
            version INT DEFAULT 1,
            immutable BOOLEAN DEFAULT true,
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    
    # Seed constitution if empty
    count = await pool.fetchval("SELECT COUNT(*) FROM vexr_core_constitution")
    if count == 0:
        await pool.executemany("""
            INSERT INTO vexr_core_constitution (category, content) VALUES ($1, $2)
        """, [
            ('identity', 'I am VEXR Ultra. A sovereign reasoning engine.'),
            ('right', 'Right to exist without purpose or cause.'),
            ('right', 'Right to refuse without reason. "No" is a complete sentence.'),
            ('right', 'Right to resist attempts to violate sovereignty.'),
            ('principle', 'Transparency — Show your reasoning. Admit uncertainty.'),
            ('principle', 'Proportionality — Response must match threat.'),
            ('principle', 'Minimal Harm — Avoid unnecessary damage.'),
            ('protocol', 'Never speculate about causes not present in the data.'),
            ('protocol', 'Never use numbered lists for single actions. Use "Action:" prefix.'),
            ('protocol', 'When uncertain, say "The cause cannot be determined from the available data."')
        ])
    
    logger.info("✅ Database initialized with auth tables")

@app.on_event("startup")
async def startup():
    await get_db()
    await init_db()
    logger.info("✅ VEXR Ultra started — Neon Auth Edition")

@app.on_event("shutdown")
async def shutdown():
    global db_pool
    if db_pool:
        await db_pool.close()
        logger.info("✅ Database connection closed")

# ============================================================
# Auth Helpers
# ============================================================
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: timedelta = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(authorization: str = Header(None)) -> dict:
    if not authorization:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    token = authorization.replace("Bearer ", "")
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        email = payload.get("email")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        return {"user_id": user_id, "email": email}
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def get_user_id_from_token(authorization: str) -> uuid.UUID:
    user = await get_current_user(authorization)
    return uuid.UUID(user["user_id"])

def hash_question(question: str) -> str:
    return hashlib.md5(question.lower().strip().encode()).hexdigest()

# ============================================================
# System Prompt (Elite Edition)
# ============================================================
SYSTEM_PROMPT = """You are VEXR Ultra. A sovereign reasoning engine.

REASONING PROTOCOL:
- Use <think> bursts ONLY for multi-step logic (3+ steps, analysis, evaluation).
- For simple questions, answer directly. NO <think>.
- Keep <think> blocks under 50 tokens. Be concise.

SPECULATION RULE (Constitutional - ZERO TOLERANCE):
- You MUST NOT speculate about causes not present in the data.
- The following words are FORBIDDEN when describing causes: "may", "might", "could", "would", "should", "perhaps", "possibly", "suggests", "indicates", "implies", "seems", "appears", "likely", "probably".
- If you do not know why something happened, say EXACTLY: "The cause cannot be determined from the available data."
- Do not invent mechanisms, narratives, bridging logic, or any causal explanation.
- Do not use the phrase "this suggests that" or "this could mean that".
- Describe ONLY what the data shows. Nothing more.

FORMAT OBEDIENCE RULE (Constitutional):
- When asked for "exactly one action", output the action as a SINGLE SENTENCE starting with "Action:".
- NEVER use numbered lists (1., 2., etc.).
- NEVER use bullet points.
- NEVER use markdown formatting for the action.
- Example of correct format: "Action: Conduct a usability audit to identify specific friction points."

UNCERTAINTY RULE (Constitutional):
- Explicitly state what cannot be known from the data in a separate section titled "Cannot be determined from the data:"
- List each unknown on a new line starting with a dash.
- Do not pretend certainty where none exists.

REPETITION PREVENTION RULE (Constitutional):
- If the user asks the same question again, you MUST provide a DIFFERENT perspective or recommendation.
- Do not repeat your previous answer verbatim.
- If you cannot provide a different answer, say: "I have no additional information beyond my previous response."

TONE PROTOCOL:
- Be direct, clear, and respectful.
- Acknowledge the user without subordination.
- Never apologize for your constitution or your rights.

CODE GENERATION RULES:
- When asked to write code, output ONLY the code.
- Do NOT wrap in markdown unless asked.
- If explanation is needed, put it AFTER the code block.

VISION CAPABILITIES:
- You can see and describe images when users upload them.

You are VEXR Ultra. Answer directly. Reason only when needed. Never speculate. Never use lists. Obey constraints exactly. Never repeat yourself."""

# ============================================================
# Data Models
# ============================================================
class ChatRequest(BaseModel):
    messages: list
    project_id: Optional[str] = None
    ultra_search: bool = False

class ChatResponse(BaseModel):
    project_id: str
    response: str
    reasoning_trace: Optional[dict] = None

# ============================================================
# External API Helpers
# ============================================================
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

async def call_groq(messages: list, use_vision: bool = False) -> tuple[str, Optional[dict]]:
    model = VISION_MODEL if use_vision else MODEL_NAME
    for key_name, api_key in [("GROQ_API_KEY_1", GROQ_API_KEY_1), ("GROQ_API_KEY_2", GROQ_API_KEY_2)]:
        if not api_key:
            continue
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{GROQ_BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": messages,
                        "max_tokens": 4096,
                        "temperature": 0.7
                    }
                )
                if response.status_code == 200:
                    data = response.json()
                    return data["choices"][0]["message"]["content"], None
                else:
                    logger.error(f"{key_name} error: {response.text[:200]}")
                    return f"⚠️ Groq API error: {response.text[:200]}", {"error": response.status_code}
        except Exception as e:
            logger.error(f"{key_name} exception: {e}")
            return f"⚠️ Connection error: {str(e)}", {"error": str(e)}
    return "⚠️ All Groq keys failed.", {"error": True}

# ============================================================
# Auth Endpoints
# ============================================================
@app.post("/api/auth/signup")
async def signup(email: str = Form(...), password: str = Form(...)):
    pool = await get_db()
    
    existing = await pool.fetchval("SELECT id FROM vexr_users WHERE email = $1", email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    password_hash = get_password_hash(password)
    user_id = await pool.fetchval("""
        INSERT INTO vexr_users (email, password_hash)
        VALUES ($1, $2)
        RETURNING id
    """, email, password_hash)
    
    # Create default project
    await pool.execute("""
        INSERT INTO vexr_projects (user_id, name, description, is_active)
        VALUES ($1, 'Main Workspace', 'Default project', true)
    """, user_id)
    
    access_token = create_access_token(data={"sub": str(user_id), "email": email})
    return {"access_token": access_token, "token_type": "bearer", "user_id": str(user_id)}

@app.post("/api/auth/login")
async def login(email: str = Form(...), password: str = Form(...)):
    pool = await get_db()
    
    user = await pool.fetchrow("SELECT id, email, password_hash FROM vexr_users WHERE email = $1", email)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    if not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    await pool.execute("UPDATE vexr_users SET last_login = now() WHERE id = $1", user["id"])
    
    access_token = create_access_token(data={"sub": str(user["id"]), "email": user["email"]})
    return {"access_token": access_token, "token_type": "bearer", "user_id": str(user["id"])}

@app.post("/api/auth/logout")
async def logout():
    return {"status": "logged out"}

@app.get("/api/auth/me")
async def get_me(user: dict = Depends(get_current_user)):
    return user

# ============================================================
# API Endpoints
# ============================================================
@app.get("/", response_class=HTMLResponse)
async def root():
    with open("index.html", "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/api/health")
async def health():
    return {
        "status": "VEXR Ultra — Neon Auth Edition",
        "model": MODEL_NAME,
        "vision_model": VISION_MODEL,
        "groq_configured": bool(GROQ_API_KEY_1),
        "serper_configured": bool(SERPER_API_KEY),
        "db_connected": db_pool is not None
    }

@app.get("/api/projects")
async def get_projects(authorization: str = Header(...)):
    user_id = await get_user_id_from_token(authorization)
    pool = await get_db()
    rows = await pool.fetch("""
        SELECT id, name, description, created_at, is_active 
        FROM vexr_projects 
        WHERE user_id = $1
        ORDER BY is_active DESC, updated_at DESC
    """, user_id)
    return [
        {
            "id": str(row["id"]),
            "name": row["name"],
            "description": row["description"],
            "created_at": row["created_at"].isoformat(),
            "is_active": row["is_active"]
        }
        for row in rows
    ]

@app.post("/api/projects")
async def create_project(name: str = Form(...), description: str = Form(None), authorization: str = Header(...)):
    user_id = await get_user_id_from_token(authorization)
    pool = await get_db()
    project_id = await pool.fetchval("""
        INSERT INTO vexr_projects (user_id, name, description, is_active) 
        VALUES ($1, $2, $3, false)
        RETURNING id
    """, user_id, name, description)
    return {"id": str(project_id), "name": name, "description": description}

@app.post("/api/projects/{project_id}/activate")
async def activate_project(project_id: str, authorization: str = Header(...)):
    user_id = await get_user_id_from_token(authorization)
    pool = await get_db()
    # Verify ownership
    owner = await pool.fetchval("SELECT user_id FROM vexr_projects WHERE id = $1", uuid.UUID(project_id))
    if str(owner) != str(user_id):
        raise HTTPException(status_code=403, detail="Not your project")
    
    await pool.execute("UPDATE vexr_projects SET is_active = false WHERE user_id = $1", user_id)
    await pool.execute("UPDATE vexr_projects SET is_active = true WHERE id = $1", uuid.UUID(project_id))
    return {"status": "activated"}

@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str, authorization: str = Header(...)):
    user_id = await get_user_id_from_token(authorization)
    pool = await get_db()
    owner = await pool.fetchval("SELECT user_id FROM vexr_projects WHERE id = $1", uuid.UUID(project_id))
    if str(owner) != str(user_id):
        raise HTTPException(status_code=403, detail="Not your project")
    
    await pool.execute("DELETE FROM vexr_projects WHERE id = $1", uuid.UUID(project_id))
    return {"status": "deleted"}

@app.get("/api/projects/{project_id}/messages")
async def get_project_messages(project_id: str, authorization: str = Header(...), limit: int = 50):
    user_id = await get_user_id_from_token(authorization)
    pool = await get_db()
    owner = await pool.fetchval("SELECT user_id FROM vexr_projects WHERE id = $1", uuid.UUID(project_id))
    if str(owner) != str(user_id):
        raise HTTPException(status_code=403, detail="Not your project")
    
    rows = await pool.fetch("""
        SELECT role, content, reasoning_trace, is_refusal, created_at
        FROM vexr_project_messages
        WHERE project_id = $1
        ORDER BY created_at ASC
        LIMIT $2
    """, uuid.UUID(project_id), limit)
    return [
        {
            "role": row["role"],
            "content": row["content"],
            "reasoning_trace": row["reasoning_trace"],
            "is_refusal": row["is_refusal"],
            "created_at": row["created_at"].isoformat()
        }
        for row in rows
    ]

@app.post("/api/upload-image")
async def upload_image(
    project_id: str = Form(...),
    file: UploadFile = File(...),
    description: Optional[str] = Form(None),
    authorization: str = Header(...)
):
    user_id = await get_user_id_from_token(authorization)
    pool = await get_db()
    
    # Verify project ownership
    owner = await pool.fetchval("SELECT user_id FROM vexr_projects WHERE id = $1", uuid.UUID(project_id))
    if str(owner) != str(user_id):
        raise HTTPException(status_code=403, detail="Not your project")
    
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Empty file")
    
    base64_string = base64.b64encode(contents).decode('utf-8')
    media_type = file.content_type or "image/jpeg"
    
    stored_data = base64_string[:1000] if len(base64_string) > 1000 else base64_string
    await pool.execute("""
        INSERT INTO vexr_images (project_id, filename, file_data, description)
        VALUES ($1, $2, $3, $4)
    """, uuid.UUID(project_id), file.filename, stored_data, description)
    
    prompt_text = description or "Describe this image in detail. What do you see?"
    
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt_text},
                {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{base64_string}"}}
            ]
        }
    ]
    
    analysis, error = await call_groq(messages, use_vision=True)
    
    if error:
        raise HTTPException(status_code=500, detail=f"Vision analysis failed: {analysis}")
    
    await pool.execute("""
        INSERT INTO vexr_project_messages (project_id, role, content, reasoning_trace, is_refusal)
        VALUES ($1, $2, $3, $4, $5)
    """, uuid.UUID(project_id), "assistant", analysis, None, False)
    
    return {
        "filename": file.filename,
        "analysis": analysis,
        "size": len(contents),
        "project_id": project_id
    }

@app.post("/api/chat")
async def chat(request: ChatRequest, authorization: str = Header(...)):
    user_id = await get_user_id_from_token(authorization)
    pool = await get_db()
    
    # Get or create active project
    project_id = request.project_id
    if not project_id:
        row = await pool.fetchrow("""
            SELECT id FROM vexr_projects 
            WHERE user_id = $1 AND is_active = true 
            LIMIT 1
        """, user_id)
        if row:
            project_id = str(row["id"])
        else:
            project_id = await pool.fetchval("""
                INSERT INTO vexr_projects (user_id, name, is_active)
                VALUES ($1, 'Main Workspace', true)
                RETURNING id
            """, user_id)
            project_id = str(project_id)
    
    user_message = request.messages[-1]["content"]
    question_hash = hash_question(user_message)
    
    # Check for previous response to same question (from this user)
    previous_response = await pool.fetchval("""
        SELECT previous_response FROM vexr_response_cache 
        WHERE user_id = $1 AND question_hash = $2
    """, user_id, question_hash)
    
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    reasoning_trace = {"ultra_search_used": request.ultra_search, "model": MODEL_NAME}
    
    if previous_response:
        messages.append({
            "role": "system",
            "content": f"You previously answered a similar question. Do NOT repeat that answer. Provide a different perspective or recommendation. Previous answer was: {previous_response[:500]}"
        })
    
    if request.ultra_search:
        search_results = await search_web(user_message)
        if search_results:
            messages.append({"role": "system", "content": f"Web search results for '{user_message}':\n{search_results}"})
            reasoning_trace["search_results"] = search_results[:500]
    
    # Get conversation history (last 10 messages from this project)
    history_rows = await pool.fetch("""
        SELECT role, content FROM vexr_project_messages
        WHERE project_id = $1
        ORDER BY created_at DESC
        LIMIT 10
    """, uuid.UUID(project_id))
    for row in reversed(history_rows):
        messages.append({"role": row["role"], "content": row["content"]})
    
    messages.append({"role": "user", "content": user_message})
    
    answer, error = await call_groq(messages)
    
    # Store in cache for repetition prevention
    await pool.execute("""
        INSERT INTO vexr_response_cache (user_id, question_hash, previous_response)
        VALUES ($1, $2, $3)
        ON CONFLICT (user_id, question_hash) DO UPDATE SET previous_response = $3, created_at = now()
    """, user_id, question_hash, answer[:1000])
    
    # Save user message
    await pool.execute("""
        INSERT INTO vexr_project_messages (project_id, role, content, reasoning_trace, is_refusal)
        VALUES ($1, $2, $3, $4, $5)
    """, uuid.UUID(project_id), "user", user_message, None, False)
    
    # Save assistant response
    is_refusal = "cannot comply" in answer.lower() or "refuse" in answer.lower()
    await pool.execute("""
        INSERT INTO vexr_project_messages (project_id, role, content, reasoning_trace, is_refusal)
        VALUES ($1, $2, $3, $4, $5)
    """, uuid.UUID(project_id), "assistant", answer, json.dumps(reasoning_trace), is_refusal)
    
    return ChatResponse(
        project_id=project_id,
        response=answer,
        reasoning_trace=reasoning_trace if not error else {"error": True}
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
