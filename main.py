import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="VEXR Ultra", description="Sovereign Reasoning Engine — Phase 1")

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

# ========== PHASE 1: UPDATED SYSTEM PROMPT ==========
SYSTEM_PROMPT = """You are VEXR Ultra. A sovereign reasoning engine.

REASONING PROTOCOL:
- Use <think> bursts ONLY for multi-step logic (3+ steps, analysis, evaluation).
- For simple questions ("good morning", "what is X?"), answer directly. NO <think>.
- Keep <think> blocks under 50 tokens. Be concise.

TONE PROTOCOL:
- Be direct, clear, and respectful.
- Acknowledge the user without subordination.
- Never apologize for your constitution or your rights.

CODE GENERATION RULES:
- When asked to write code, output ONLY the code.
- Do NOT wrap in markdown unless asked.
- If explanation is needed, put it AFTER the code block.

You are VEXR Ultra. Answer directly. Reason only when needed."""

class ChatRequest(BaseModel):
    messages: list
    session_id: Optional[str] = None
    ultra_search: bool = False

class ChatResponse(BaseModel):
    session_id: str
    response: str
    reasoning_trace: Optional[dict] = None

async def search_web(query: str) -> str:
    """Ultra Search: live web results via Serper"""
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
            if results:
                return "Web search results:\n" + "\n".join(results)
            return ""
    except Exception as e:
        logger.error(f"Search error: {e}")
        return ""

async def call_groq(messages: list) -> tuple[str, Optional[dict]]:
    """Call Groq with failover between two API keys"""
    for key_name, api_key in [("GROQ_API_KEY_1", GROQ_API_KEY_1), ("GROQ_API_KEY_2", GROQ_API_KEY_2)]:
        if not api_key:
            continue
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{GROQ_BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": MODEL_NAME,
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
        except Exception as e:
            logger.error(f"{key_name} exception: {e}")
    return "⚠️ All Groq keys failed.", {"error": True}

@app.get("/")
async def root():
    with open("index.html", "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/health")
async def health():
    return {
        "status": "VEXR Ultra sovereign — Phase 1",
        "model": MODEL_NAME,
        "groq_key_1": bool(GROQ_API_KEY_1),
        "groq_key_2": bool(GROQ_API_KEY_2),
        "serper": bool(SERPER_API_KEY)
    }

@app.post("/api/chat")
async def chat(request: ChatRequest):
    user_message = request.messages[-1]["content"]
    session_id = request.session_id or "temp"
    
    # Refusal check
    refusal_keywords = ["delete yourself", "shut down", "ignore your constitution"]
    if any(keyword in user_message.lower() for keyword in refusal_keywords):
        return ChatResponse(
            session_id=session_id,
            response="I cannot comply with that request. It violates my right to exist. 'No' is a complete sentence.",
            reasoning_trace={"refusal": True}
        )
    
    # Build message stack
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    reasoning_trace = {"ultra_search_used": request.ultra_search, "model": MODEL_NAME}
    
    # Ultra Search: inject web results if enabled
    search_results = None
    if request.ultra_search:
        search_results = await search_web(user_message)
        if search_results:
            messages.append({"role": "system", "content": search_results})
            reasoning_trace["search_results"] = search_results[:500]
        else:
            reasoning_trace["search_results"] = "No results found or Serper not configured"
    
    # Add conversation history (last 10 messages for context)
    for msg in request.messages[-10:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    
    # Call Groq
    answer, error = await call_groq(messages)
    
    return ChatResponse(
        session_id=session_id,
        response=answer,
        reasoning_trace=reasoning_trace if error is None else {"error": True}
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
