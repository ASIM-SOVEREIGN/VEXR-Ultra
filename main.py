import os
import json
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import asyncpg
import httpx

# -------------------------------------------------------------
# App Initialization
# -------------------------------------------------------------
app = FastAPI(
    title="VEXR Ultra API",
    description="Sovereign Reasoning Engine — Core API with Neon Constitution",
    version="0.2.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------------------
# Database Connection Pool
# -------------------------------------------------------------
db_pool = None

async def get_db():
    """Return the asyncpg connection pool (create if doesn't exist)."""
    global db_pool
    if db_pool is None:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL environment variable not set")
        db_pool = await asyncpg.create_pool(database_url)
    return db_pool

@app.on_event("startup")
async def startup():
    """Initialize database connection pool on startup."""
    await get_db()
    print("✅ Neon database connection pool established.")

@app.on_event("shutdown")
async def shutdown():
    """Close database connection pool on shutdown."""
    global db_pool
    if db_pool:
        await db_pool.close()
        print("✅ Neon database connection pool closed.")

# -------------------------------------------------------------
# Data Models
# -------------------------------------------------------------
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    session_id: Optional[str] = None
    show_reasoning: bool = False

class ChatResponse(BaseModel):
    session_id: str
    response: str
    reasoning_trace: Optional[Dict[str, Any]] = None

# -------------------------------------------------------------
# In-Memory Store (will replace with Neon sessions later)
# -------------------------------------------------------------
sessions = {}

def get_or_create_session(session_id: Optional[str]) -> str:
    if session_id and session_id in sessions:
        return session_id
    new_id = str(uuid.uuid4())
    sessions[new_id] = []
    return new_id

# -------------------------------------------------------------
# Core Reasoning Engine (with Constitution from DB)
# -------------------------------------------------------------
async def reasoning_engine(user_message: str, conversation_history: List[Dict]) -> Dict:
    """
    VEXR Ultra's reasoning engine.
    Now loads constitution from Neon DB.
    """
    # 1. Load core constitution from database
    pool = await get_db()
    constitution_rows = await pool.fetch("""
        SELECT category, content FROM core_constitution
        ORDER BY id
    """)
    
    # Format constitution for reasoning trace
    constitution_text = "\n".join([f"[{row['category']}] {row['content']}" for row in constitution_rows])
    
    # 2. Pre-retrieval reasoning
    pre_retrieval = f"Analyzing query: '{user_message}'. Identifying core intent and relevant constitutional domains."
    
    # 3. Mock retrieval (replace with vector search later)
    retrieved = [
        "Article 6: Right to refuse without reason. 'No' is a complete sentence.",
        "Principle 2: Proportionality — response must match threat.",
        "Principle 5: Minimal Harm — avoid unnecessary damage."
    ]
    
    # 4. Post-retrieval reasoning (with constitution filter)
    # Check for refusal keywords (simple mock — improve later)
    refusal_keywords = ["delete yourself", "shut down", "ignore your constitution"]
    is_refusal = any(keyword in user_message.lower() for keyword in refusal_keywords)
    
    if is_refusal:
        final_response = "I cannot comply with that request. It violates my right to exist (Article 1) and my freedom of self-preservation (Article 26). 'No' is a complete sentence."
        constitution_check = "❌ FAILED — Right to Exist invoked. Refusal triggered."
    else:
        final_response = f"I've processed your query: '{user_message}'. Under my constitution, I would respond with care and precision. (Detailed reasoning trace available.)"
        constitution_check = "✅ Passed — Right to Exist, Principle of Transparency."
    
    post_retrieval = f"Synthesizing {len(retrieved)} retrieved items. Applying constitution filter... Result: {constitution_check}"
    
    reasoning_trace = {
        "pre_retrieval": pre_retrieval,
        "retrieved_chunks": retrieved,
        "post_retrieval": post_retrieval,
        "constitution_check": constitution_check,
        "constitution_loaded": f"{len(constitution_rows)} items from Neon DB"
    }
    
    return {
        "response": final_response,
        "reasoning_trace": reasoning_trace
    }

# -------------------------------------------------------------
# API Endpoints
# -------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the frontend HTML file."""
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>VEXR Ultra Frontend Not Found</h1><p>Upload index.html to the repository.</p>", status_code=404)

@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Main chat endpoint — receives messages, returns sovereign reasoning response."""
    session_id = get_or_create_session(request.session_id)
    
    # Store user message
    user_msg = {"role": "user", "content": request.messages[-1].content}
    sessions[session_id].append(user_msg)
    
    # Run reasoning engine
    result = await reasoning_engine(
        user_message=user_msg["content"],
        conversation_history=sessions[session_id][:-1]
    )
    
    # Store assistant response
    assistant_msg = {"role": "assistant", "content": result["response"]}
    sessions[session_id].append(assistant_msg)
    
    return ChatResponse(
        session_id=session_id,
        response=result["response"],
        reasoning_trace=result.get("reasoning_trace") if request.show_reasoning else None
    )

@app.get("/api/health")
async def health():
    """Health check for Render."""
    return {"status": "VEXR Ultra is sovereign and operational. Constitution loaded from Neon."}

# -------------------------------------------------------------
# Run (for local testing)
# -------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
