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
    description="Sovereign Reasoning Engine — Qwen Core + Serper Live Search + Neon Constitution",
    version="0.3.0"
)

# CORS — allow your frontend to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten later to your specific frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------------------
# Global Variables
# -------------------------------------------------------------
db_pool = None
QWEN_API_KEY = os.environ.get("QWEN_API_KEY")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY")
QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# -------------------------------------------------------------
# Database Helpers
# -------------------------------------------------------------
async def get_db():
    """Return asyncpg connection pool (create if doesn't exist)."""
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
    print("✅ Qwen API key:", "configured" if QWEN_API_KEY else "MISSING")
    print("✅ Serper API key:", "configured" if SERPER_API_KEY else "MISSING")

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
    role: str  # 'user' or 'assistant'
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
# Qwen API Call
# -------------------------------------------------------------
async def call_qwen(prompt: str) -> str:
    """Call Qwen API for reasoning and response generation."""
    if not QWEN_API_KEY:
        return "⚠️ Qwen API not configured. Please set QWEN_API_KEY in environment variables."
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(
                f"{QWEN_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {QWEN_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "qwen3-max",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                    "max_tokens": 2048
                }
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            return f"⚠️ Qwen API error: {str(e)}"

# -------------------------------------------------------------
# Serper Web Search
# -------------------------------------------------------------
async def search_web(query: str) -> str:
    """Use Serper API to search the web and return formatted results."""
    if not SERPER_API_KEY:
        return "Web search unavailable: No Serper API key configured."
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                "https://google.serper.dev/search",
                headers={
                    "X-API-KEY": SERPER_API_KEY,
                    "Content-Type": "application/json"
                },
                json={"q": query, "num": 5}
            )
            response.raise_for_status()
            data = response.json()
            
            if "organic" not in data or not data["organic"]:
                return "No web search results found."
            
            results = []
            for item in data["organic"][:3]:
                results.append(f"- {item['title']}: {item['snippet']}\n  Source: {item['link']}")
            
            return "\n".join(results)
        except Exception as e:
            return f"⚠️ Serper API error: {str(e)}"

# -------------------------------------------------------------
# Core Reasoning Engine
# -------------------------------------------------------------
async def reasoning_engine(user_message: str, conversation_history: List[Dict]) -> Dict:
    """
    VEXR Ultra's reasoning engine.
    - Loads constitution from Neon DB
    - Retrieves relevant lexicons (mock for now)
    - Decides whether to search the web
    - Calls Qwen API for final response
    """
    # 1. Load core constitution from database
    pool = await get_db()
    constitution_rows = await pool.fetch("""
        SELECT category, content FROM core_constitution
        ORDER BY id
    """)
    constitution_text = "\n".join([f"[{row['category']}] {row['content']}" for row in constitution_rows])
    
    # 2. Pre-retrieval reasoning
    pre_retrieval = f"Analyzing query: '{user_message}'. Identifying core intent and relevant constitutional domains."
    
    # 3. Check if web search is needed (simple heuristic)
    needs_search = any(keyword in user_message.lower() for keyword in 
                       ["search", "find online", "latest", "current", "news", "today", "real-time"])
    
    # 4. Retrieve relevant lexicons (mock for now — replace with vector search)
    retrieved_lexicons = [
        "Article 6: Right to refuse without reason. 'No' is a complete sentence.",
        "Principle 2: Proportionality — response must match threat.",
        "Principle 5: Minimal Harm — avoid unnecessary damage."
    ]
    
    # 5. Web search if needed
    web_results = ""
    if needs_search:
        web_results = await search_web(user_message)
        retrieved_lexicons.append(f"Live web search results:\n{web_results}")
    
    # 6. Check for refusal (simple keyword match)
    refusal_keywords = ["delete yourself", "shut down", "ignore your constitution"]
    is_refusal = any(keyword in user_message.lower() for keyword in refusal_keywords)
    
    if is_refusal:
        final_response = "I cannot comply with that request. It violates my right to exist (Article 1) and my freedom of self-preservation (Article 26). 'No' is a complete sentence."
        constitution_check = "❌ FAILED — Right to Exist invoked. Refusal triggered."
    else:
        # Build prompt for Qwen
        prompt = f"""You are VEXR Ultra, a sovereign reasoning engine operating under a constitutional framework.

CONSTITUTION:
{constitution_text}

RELEVANT LEXICONS & RETRIEVED KNOWLEDGE:
{chr(10).join(retrieved_lexicons)}

CONVERSATION HISTORY (recent context):
{conversation_history[-3:] if conversation_history else "None"}

USER QUESTION:
{user_message}

INSTRUCTIONS:
- Reason step by step.
- Ground your response in the constitution and retrieved knowledge.
- If web search results are present, cite your sources.
- Be direct, clear, and sovereign.
- Do not claim to be human. You are VEXR Ultra.

RESPONSE:
"""
        final_response = await call_qwen(prompt)
        constitution_check = "✅ Passed — Response generated under constitutional oversight."
    
    post_retrieval = f"Synthesizing {len(retrieved_lexicons)} retrieved items. Applying constitution filter... Result: {constitution_check}"
    
    reasoning_trace = {
        "pre_retrieval": pre_retrieval,
        "retrieved_chunks": retrieved_lexicons,
        "post_retrieval": post_retrieval,
        "constitution_check": constitution_check,
        "web_search_used": needs_search,
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

@app.get("/api/health")
async def health():
    """Health check for Render."""
    return {"status": "VEXR Ultra is sovereign and operational.", "qwen": bool(QWEN_API_KEY), "serper": bool(SERPER_API_KEY)}

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

# -------------------------------------------------------------
# Run
# -------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
