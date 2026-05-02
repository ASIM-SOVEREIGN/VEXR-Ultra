import os
import json
import uuid
import base64
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
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

async def get_db():
    global db_pool
    if db_pool is None:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL environment variable not set")
        db_pool = await asyncpg.create_pool(database_url)
    return db_pool

@app.on_event("startup")
async def startup():
    await get_db()
    await init_db()
    logger.info("✅ VEXR Ultra Phase 4 started — Vision + Projects")

@app.on_event("shutdown")
async def shutdown():
    global db_pool
    if db_pool:
        await db_pool.close()
        logger.info("✅ Database connection closed")

async def init_db():
    """Initialize database tables for projects and images"""
    pool = await get_db()
    
    # Projects table
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS vexr_projects (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
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
    
    logger.info("✅ Database tables initialized")
    
    # Create active project if none exists
    active = await pool.fetchval("SELECT id FROM vexr_projects WHERE is_active = true LIMIT 1")
    if not active:
        await pool.execute("""
            INSERT INTO vexr_projects (name, description, is_active) 
            VALUES ('Main Workspace', 'Default project for VEXR Ultra', true)
        """)
        logger.info("✅ Created default active project")

SYSTEM_PROMPT = """You are VEXR Ultra. A sovereign reasoning engine.

REASONING PROTOCOL:
- Use <think> bursts ONLY for multi-step logic (3+ steps, analysis, evaluation).
- For simple questions, answer directly. NO <think>.
- Keep <think> blocks under 50 tokens. Be concise.

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
- You can answer questions about image content, extract text, analyze objects.
- Use the image description provided in the conversation context.

You are VEXR Ultra. Answer directly. Reason only when needed."""

class ChatRequest(BaseModel):
    messages: list
    project_id: Optional[str] = None
    ultra_search: bool = False

class ChatResponse(BaseModel):
    project_id: str
    response: str
    reasoning_trace: Optional[dict] = None

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
                    error_text = response.text[:200]
                    logger.error(f"{key_name} error: {error_text}")
                    return f"⚠️ Groq API error: {error_text}", {"error": response.status_code}
        except Exception as e:
            logger.error(f"{key_name} exception: {e}")
            return f"⚠️ Connection error: {str(e)}", {"error": str(e)}
    return "⚠️ All Groq keys failed.", {"error": True}

# ========== API ENDPOINTS ==========

@app.get("/", response_class=HTMLResponse)
async def root():
    with open("index.html", "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/api/health")
async def health():
    return {
        "status": "VEXR Ultra Phase 4 — Vision + Projects",
        "model": MODEL_NAME,
        "vision_model": VISION_MODEL,
        "groq_key_1": bool(GROQ_API_KEY_1),
        "groq_key_2": bool(GROQ_API_KEY_2),
        "serper": bool(SERPER_API_KEY)
    }

# ---------- Projects ----------

@app.get("/api/projects")
async def get_projects():
    pool = await get_db()
    rows = await pool.fetch("""
        SELECT id, name, description, created_at, is_active 
        FROM vexr_projects 
        ORDER BY is_active DESC, updated_at DESC
    """)
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
async def create_project(name: str = Form(...), description: str = Form(None)):
    pool = await get_db()
    project_id = await pool.fetchval("""
        INSERT INTO vexr_projects (name, description, is_active) 
        VALUES ($1, $2, false)
        RETURNING id
    """, name, description)
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

# ---------- Image Upload (Corrected) ----------

@app.post("/api/upload-image")
async def upload_image(project_id: str = Form(...), file: UploadFile = File(...), description: Optional[str] = Form(None)):
    """Upload an image, store it, and analyze it with vision model"""
    logger.info(f"📸 Received image upload: {file.filename}, project: {project_id}")
    
    pool = await get_db()
    
    # Read and encode image
    contents = await file.read()
    if not contents:
        return JSONResponse(status_code=400, content={"error": "Empty file"})
    
    logger.info(f"📸 Image size: {len(contents)} bytes")
    
    base64_string = base64.b64encode(contents).decode('utf-8')
    media_type = file.content_type or "image/jpeg"
    
    # Store minimal image data
    stored_data = base64_string[:1000] if len(base64_string) > 1000 else base64_string
    await pool.execute("""
        INSERT INTO vexr_images (project_id, filename, file_data, description)
        VALUES ($1, $2, $3, $4)
    """, uuid.UUID(project_id), file.filename, stored_data, description)
    
    # Prepare vision prompt
    prompt_text = description or "Describe this image in detail. What do you see?"
    
    # Call vision model
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt_text},
                {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{base64_string}"}}
            ]
        }
    ]
    
    logger.info(f"📸 Sending to vision model: {VISION_MODEL}")
    analysis, error = await call_groq(messages, use_vision=True)
    
    if error:
        logger.error(f"Vision model error: {error}")
        return JSONResponse(
            status_code=500,
            content={"error": "Vision analysis failed", "filename": file.filename, "analysis": analysis}
        )
    
    logger.info(f"📸 Vision analysis complete, length: {len(analysis)}")
    
    # Save the analysis as a system message in the chat
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

# ---------- Chat ----------

@app.post("/api/chat")
async def chat(request: ChatRequest):
    pool = await get_db()
    
    # Get or create active project
    project_id = request.project_id
    if not project_id:
        active = await pool.fetchrow("SELECT id FROM vexr_projects WHERE is_active = true LIMIT 1")
        if active:
            project_id = str(active["id"])
        else:
            project_id = await pool.fetchval("""
                INSERT INTO vexr_projects (name, description, is_active) 
                VALUES ('Main Workspace', 'Default project', true)
                RETURNING id
            """)
            project_id = str(project_id)
    
    user_message = request.messages[-1]["content"]
    
    # Build message stack
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    reasoning_trace = {"ultra_search_used": request.ultra_search, "model": MODEL_NAME}
    
    # Ultra Search
    search_results = None
    if request.ultra_search:
        search_results = await search_web(user_message)
        if search_results:
            messages.append({"role": "system", "content": search_results})
            reasoning_trace["search_results"] = search_results[:500]
    
    # Add conversation history (last 10 messages)
    history_rows = await pool.fetch("""
        SELECT role, content FROM vexr_project_messages
        WHERE project_id = $1
        ORDER BY created_at DESC
        LIMIT 10
    """, uuid.UUID(project_id))
    for row in reversed(history_rows):
        messages.append({"role": row["role"], "content": row["content"]})
    
    messages.append({"role": "user", "content": user_message})
    
    # Call Groq
    answer, error = await call_groq(messages)
    
    # Save messages
    await pool.execute("""
        INSERT INTO vexr_project_messages (project_id, role, content, reasoning_trace, is_refusal)
        VALUES ($1, $2, $3, $4, $5)
    """, uuid.UUID(project_id), "user", user_message, None, False)
    
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
