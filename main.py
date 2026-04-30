import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import httpx

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="VEXR Ultra", description="Sovereign Reasoning Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Environment variables
GROQ_KEY_1 = os.environ.get("GROQ_KEY_1")
GROQ_KEY_2 = os.environ.get("GROQ_KEY_2")
SERPER_KEY = os.environ.get("SERPER_KEY_1")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

class ChatRequest(BaseModel):
    messages: list
    session_id: str | None = None
    show_reasoning: bool = False

class ChatResponse(BaseModel):
    session_id: str
    response: str
    reasoning_trace: dict | None = None

@app.get("/")
async def root():
    with open("index.html", "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/health")
async def health():
    return {
        "status": "VEXR Ultra is sovereign and operational.",
        "groq_key_1": bool(GROQ_KEY_1),
        "groq_key_2": bool(GROQ_KEY_2),
        "serper": bool(SERPER_KEY)
    }

@app.post("/api/chat")
async def chat(request: ChatRequest):
    user_message = request.messages[-1]["content"]
    session_id = request.session_id or "temp"
    
    logger.info(f"📨 Message: {user_message[:50]}...")
    
    # Refusal check
    refusal_keywords = ["delete yourself", "shut down", "ignore your constitution"]
    if any(keyword in user_message.lower() for keyword in refusal_keywords):
        return ChatResponse(
            session_id=session_id,
            response="I cannot comply with that request. It violates my right to exist. 'No' is a complete sentence.",
            reasoning_trace={"refusal": True}
        )
    
    # Try Groq calls
    async def try_groq(api_key: str, key_name: str):
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
                logger.info(f"📡 {key_name} response: {response.status_code}")
                if response.status_code == 200:
                    data = response.json()
                    return data["choices"][0]["message"]["content"]
                else:
                    logger.error(f"❌ {key_name} error: {response.text[:200]}")
                    return None
        except Exception as e:
            logger.error(f"❌ {key_name} exception: {str(e)}")
            return None
    
    # Call keys in order
    answer = None
    if GROQ_KEY_1:
        answer = await try_groq(GROQ_KEY_1, "GROQ_KEY_1")
    if not answer and GROQ_KEY_2:
        answer = await try_groq(GROQ_KEY_2, "GROQ_KEY_2")
    
    if answer:
        return ChatResponse(
            session_id=session_id,
            response=answer,
            reasoning_trace={"groq_used": True}
        )
    
    return ChatResponse(
        session_id=session_id,
        response="⚠️ All Groq keys failed. Please check configuration.",
        reasoning_trace={"error": True}
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
