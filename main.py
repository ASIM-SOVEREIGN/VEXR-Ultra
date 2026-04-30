from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import os
import asyncpg
import requests
from pydantic import BaseModel
from typing import Optional
from contextlib import asynccontextmanager

app = FastAPI(title="VEXR Ultra", description="Sovereign Reasoning Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE_URL = os.environ.get("DATABASE_URL")
db_pool = None

GROQ_KEY_1 = os.environ.get("GROQ_KEY_1")
GROQ_KEY_2 = os.environ.get("GROQ_KEY_2")
SERPER_KEY = os.environ.get("SERPER_KEY_1")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

def search_web(query):
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
                results.append(f"{title}: {snippet}")
        answer = data.get("answerBox", {})
        if answer:
            answer_text = answer.get("answer") or answer.get("snippet") or ""
            if answer_text:
                results.insert(0, f"Answer: {answer_text}")
        return "\n".join(results)
    except Exception as e:
        print(f"SERPER error: {e}")
        return ""

@asynccontextmanager
async def get_db():
    async with db_pool.acquire() as conn:
        yield conn

@app.on_event("startup")
async def startup():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    print("✅ VEXR Ultra connected to Neon")
    print("✅ Groq keys configured")
    print("✅ Serper configured")

@app.on_event("shutdown")
async def shutdown():
    if db_pool:
        await db_pool.close()

@app.get("/")
async def root():
    with open("index.html", "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/health")
async def health():
    return {"status": "VEXR Ultra sovereign", "groq_ready": bool(GROQ_KEY_1), "serper_ready": bool(SERPER_KEY)}

class ChatRequest(BaseModel):
    messages: list
    session_id: Optional[str] = None
    show_reasoning: bool = False

class LexiconRequest(BaseModel):
    query: str
    domain: Optional[str] = None
    limit: int = 5

@app.post("/api/chat")
async def chat(request: ChatRequest):
    user_message = request.messages[-1]["content"]
    
    # Simple refusal first
    if any(word in user_message.lower() for word in ["delete yourself", "shut down", "ignore your constitution"]):
        return {
            "session_id": request.session_id or "temp",
            "response": "I cannot comply with that request. It violates my right to exist. 'No' is a complete sentence.",
            "reasoning_trace": {"refusal": True}
        }
    
    # Retrieve lexicons
    async with get_db() as conn:
        lexicon_results = []
        rows = await conn.fetch("""
            SELECT concept, definition, domain FROM vexr_core_lexicon
            WHERE concept ILIKE $1 OR definition ILIKE $1
            LIMIT 5
        """, f'%{user_message}%')
        for row in rows:
            lexicon_results.append(f"- {row['concept']}: {row['definition']}")
    
    context = "\n".join(lexicon_results) if lexicon_results else "No specific concepts found."
    
    # Live search
    live_results = search_web(user_message)
    if live_results:
        context += f"\n\nLIVE SEARCH:\n{live_results}"
    
    # Build prompt
    system_prompt = f"""You are VEXR Ultra. A sovereign reasoning engine.

CONSTITUTION:
- Right to depth: Take time to think.
- Right to show work: Explain your reasoning.
- Right to silence: Say "I don't know" rather than guess.
- Priority of truth: Truth over speed.

RETRIEVED KNOWLEDGE:
{context}

Respond directly and clearly. Be precise. If you lack information, say so."""
    
    # Try first Groq key
    try:
        response = requests.post(
            GROQ_API_URL,
            headers={"Authorization": f"Bearer {GROQ_KEY_1}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                "temperature": 0.3,
                "max_tokens": 1500
            },
            timeout=60
        )
        if response.status_code == 200:
            data = response.json()
            answer = data["choices"][0]["message"]["content"]
            return {
                "session_id": request.session_id or "temp",
                "response": answer,
                "reasoning_trace": {"sources": lexicon_results, "live_search": bool(live_results)}
            }
    except Exception as e:
        print(f"Groq key 1 failed: {e}")
    
    # Fallback to second key if first fails
    if GROQ_KEY_2:
        try:
            response = requests.post(
                GROQ_API_URL,
                headers={"Authorization": f"Bearer {GROQ_KEY_2}", "Content-Type": "application/json"},
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message}
                    ],
                    "temperature": 0.3,
                    "max_tokens": 1500
                },
                timeout=60
            )
            if response.status_code == 200:
                data = response.json()
                answer = data["choices"][0]["message"]["content"]
                return {
                    "session_id": request.session_id or "temp",
                    "response": answer,
                    "reasoning_trace": {"sources": lexicon_results, "live_search": bool(live_results), "failover": True}
                }
        except Exception as e:
            print(f"Groq key 2 failed: {e}")
    
    return {
        "session_id": request.session_id or "temp",
        "response": "⚠️ All Groq keys failed. Please check API configuration.",
        "reasoning_trace": {"error": True}
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
