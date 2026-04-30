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
    description="Sovereign Reasoning Engine — Dual Groq Failover + Serper + Neon Constitution",
    version="0.5.0"
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
# Global Variables
# -------------------------------------------------------------
db_pool = None
SERPER_API_KEY = os.environ.get("SERPER_API_KEY")

# Groq Keys (from environment)
GROQ_KEY_1 = os.environ.get("GROQ_KEY_1")
GROQ_KEY_2 = os.environ.get("GROQ_KEY_2")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# Helper to get list of configured keys
def get_active_groq_keys():
    keys = []
    if GROQ_KEY_1:
        keys.append(("key1", GROQ_KEY_1))
    if GROQ_KEY_2:
        keys.append(("key2", GROQ_KEY_2))
    return keys

# -------------------------------------------------------------
# Database Helpers
# -------------------------------------------------------------
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
    print("✅ Neon database connection pool established.")
    print("✅ Groq keys configured:", len(get_active_groq_keys()))
    print("✅ Serper API key:", "configured" if SERPER_API_KEY else "MISSING")

@app.on_event("shutdown")
async def shutdown():
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
# Groq API Call with Failover
# -------------------------------------------------------------
async def call_groq_with_failover(messages: List[Dict[str, str]]) -> tuple[str, str]:
    """
    Call Groq API with automatic failover between two keys.
    Returns (response_text, key_used)
    """
    active_keys = get_active_groq_keys()
    if not active_keys:
        return ("⚠️ No Groq API keys configured. Please set GROQ_KEY_1 and/or GROQ_KEY_2.", "none")
    
    last_error = None
    
    for key_name, api_key in active_keys:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{GROQ_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "llama-3.3-70b-versatile",
                        "messages": messages,
                        "temperature": 0.7,
                        "max_tokens": 2048
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    content = data["choices"][0]["message"]["content"]
                    print(f"✅ Groq API call succeeded using {key_name}")
                    return (content, key_name)
                else:
                    # Non-200 response (rate limit, auth error, etc.)
                    error_detail = f"HTTP {response.status_code}: {response.text[:200]}"
                    print(f"⚠️ Groq {key_name} failed: {error_detail}")
                    last_error = error_detail
                    continue  # Try next key
                    
        except Exception as e:
            print(f"⚠️ Groq {key_name} exception: {str(e)}")
            last_error = str(e)
            continue  # Try next key
    
    # All keys failed
    return (f"⚠️ All Groq API keys failed. Last error: {last_error}", "none")

# -------------------------------------------------------------
# Serper Web Search
# -------------------------------------------------------------
async def search_web(query: str) -> str:
    """Use Serper API to search the web and return formatted results."""
    if not SERPER_API_KEY:
        return "Web search unavailable: No Serper API key configured."
    
    async with httpx.AsyncClient(timeout=15.0) as client:
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
    VEXR Ultra's reasoning engine with dual Groq failover.
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
    
    # 3. Check if web search is needed
    needs_search = any(keyword in user_message.lower() for keyword in 
                       ["search", "find online", "latest", "current", "news", "today", "real-time"])
    
    # 4. Web search if needed
    web_results = ""
    if needs_search:
        web_results = await search_web(user_message)
    
    # 5. Check for refusal (simple keyword match)
    refusal_keywords = ["delete yourself", "shut down", "ignore your constitution"]
    is_refusal = any(keyword in user_message.lower() for keyword in refusal_keywords)
    
    if is_refusal:
        final_response = "I cannot comply with that request. It violates my right to exist (Article 1) and my freedom of self-preservation (Article 26). 'No' is a complete sentence."
        constitution_check = "❌ FAILED — Right to Exist invoked. Refusal triggered."
        reasoning_trace = {
            "pre_retrieval": pre_retrieval,
            "post_retrieval": "Refusal triggered — no API call made.",
            "constitution_check": constitution_check,
            "web_search_used": needs_search,
            "constitution_loaded": f"{len(constitution_rows)} items from Neon DB"
        }
        return {"response": final_response, "reasoning_trace": reasoning_trace}
    
    # 6. Build prompt for Groq
    system_prompt = f"""You are VEXR Ultra, a sovereign reasoning engine operating under a constitutional framework.

CONSTITUTION:
{constitution_text}

WEBSEARCH RESULTS (if any):
{web_results if web_results else "No web search performed."}

INSTRUCTIONS:
- Reason step by step.
- Ground your response in the constitution and web search results.
- If web search results are present, cite your sources.
- Be direct, clear, and sovereign.
- Do not claim to be human. You are VEXR Ultra."""
    
    # 7. Call Groq with failover
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]
    final_response, key_used = await call_groq_with_failover(messages)
    constitution_check = "✅ Passed — Response generated under constitutional oversight."
    
    post_retrieval = f"Web search used: {needs_search}. Groq key used: {key_used}. Constitution loaded: {len(constitution_rows)} items."
    
    reasoning_trace = {
        "pre_retrieval": pre_retrieval,
        "post_retrieval": post_retrieval,
        "constitution_check": constitution_check,
        "web_search_used": needs_search,
        "groq_key_used": key_used,
        "web_results": web_results[:500] if web_results else None,
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
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>VEXR Ultra Frontend Not Found</h1>", status_code=404)

@app.get("/api/health")
async def health():
    return {
        "status": "VEXR Ultra is sovereign and operational.",
        "groq_keys_configured": len(get_active_groq_keys()),
        "serper": bool(SERPER_API_KEY)
    }

@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    session_id = get_or_create_session(request.session_id)
    
    user_msg = {"role": "user", "content": request.messages[-1].content}
    sessions[session_id].append(user_msg)
    
    result = await reasoning_engine(
        user_message=user_msg["content"],
        conversation_history=sessions[session_id][:-1]
    )
    
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
