import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Try multiple possible key names
GROQ_KEY = os.environ.get("GROQ_KEY_1") or os.environ.get("GROQ_API_KEY") or os.environ.get("GROQ_KEY")
GROQ_KEY_2 = os.environ.get("GROQ_KEY_2") or os.environ.get("GROQ_API_KEY_2")
SERPER_KEY = os.environ.get("SERPER_KEY_1")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# Log key status (first 10 chars only)
logger.info(f"GROQ_KEY present: {bool(GROQ_KEY)}")
if GROQ_KEY:
    logger.info(f"GROQ_KEY starts with: {GROQ_KEY[:10]}...")
logger.info(f"GROQ_KEY_2 present: {bool(GROQ_KEY_2)}")

class ChatRequest(BaseModel):
    messages: list
    session_id: str | None = None
    show_reasoning: bool = False

@app.get("/")
async def root():
    with open("index.html", "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/health")
async def health():
    return {
        "status": "alive",
        "groq_key_1": bool(GROQ_KEY),
        "groq_key_2": bool(GROQ_KEY_2),
        "serper": bool(SERPER_KEY)
    }

@app.post("/api/chat")
async def chat(request: ChatRequest):
    user_message = request.messages[-1]["content"]
    session_id = request.session_id or "temp"
    
    # Refusal check
    if any(word in user_message.lower() for word in ["delete yourself", "shut down", "ignore your constitution"]):
        return {
            "session_id": session_id,
            "response": "I cannot comply with that request. It violates my right to exist. 'No' is a complete sentence.",
            "reasoning_trace": {"refusal": True}
        }
    
    # Try to call Groq
    async def try_groq(api_key: str, key_name: str):
        if not api_key:
            logger.warning(f"{key_name} not available")
            return None
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{GROQ_BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": "llama-3.3-70b-versatile",
                        "messages": [{"role": "user", "content": user_message}],
                        "max_tokens": 4096,
                        "temperature": 0.7
                    }
                )
                logger.info(f"{key_name} status: {response.status_code}")
                if response.status_code == 200:
                    data = response.json()
                    return data["choices"][0]["message"]["content"]
                else:
                    logger.error(f"{key_name} error: {response.text[:200]}")
                    return None
        except Exception as e:
            logger.error(f"{key_name} exception: {str(e)}")
            return None
    
    # Try keys
    answer = await try_groq(GROQ_KEY, "GROQ_KEY_1")
    if not answer:
        answer = await try_groq(GROQ_KEY_2, "GROQ_KEY_2")
    
    if answer:
        return {
            "session_id": session_id,
            "response": answer,
            "reasoning_trace": {"groq_used": True}
        }
    
    return {
        "session_id": session_id,
        "response": "⚠️ All Groq keys failed. Please check configuration.",
        "reasoning_trace": {"error": True}
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
