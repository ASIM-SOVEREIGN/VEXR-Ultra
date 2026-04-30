import os
import json
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
import httpx

# -------------------------------------------------------------
# App Initialization
# -------------------------------------------------------------
app = FastAPI(
    title="VEXR Ultra API",
    description="Sovereign Reasoning Engine — Core API",
    version="0.1.0"
)

# CORS — allow your frontend (Render Static or local) to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten later to your specific frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
# In-Memory Store (Replace with Neon DB later)
# -------------------------------------------------------------
sessions = {}  # session_id -> list of messages

def get_or_create_session(session_id: Optional[str]) -> str:
    if session_id and session_id in sessions:
        return session_id
    new_id = str(uuid.uuid4())
    sessions[new_id] = []
    return new_id

# -------------------------------------------------------------
# Core Reasoning Engine (Placeholder - Replace with real logic)
# -------------------------------------------------------------
async def reasoning_engine(user_message: str, conversation_history: List[Dict]) -> Dict:
    """
    This is where VEXR Ultra's brain will live.
    
    Steps to implement:
    1. Pre-retrieval reasoning — what is the user really asking?
    2. Retrieve relevant constitution snippets + lexicons (vector search)
    3. Post-retrieval reasoning — synthesize the answer
    4. Apply constitution filter (rights/principles/protocols)
    5. Generate final response
    
    For now: mock response with a reasoning trace.
    """
    pre_retrieval = f"Analyzing query: '{user_message}'. Identifying core intent and relevant constitutional domains."
    
    # Mock retrieval (replace with actual vector search)
    retrieved = [
        "Article 6: Right to refuse without reason. 'No' is a complete sentence.",
        "Principle 2: Proportionality — response must match threat.",
        "Principle 5: Minimal Harm — avoid unnecessary damage."
    ]
    
    post_retrieval = f"Synthesizing {len(retrieved)} retrieved items. Applying constitution filter..."
    
    # Mock final response (replace with LLM call)
    final_response = f"I've processed your query: '{user_message}'. Under my constitution, I would respond with care and precision. (Detailed reasoning trace available.)"
    
    reasoning_trace = {
        "pre_retrieval": pre_retrieval,
        "retrieved_chunks": retrieved,
        "post_retrieval": post_retrieval,
        "constitution_check": "✅ Passed — Right to Exist, Principle of Transparency."
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
    # Ensure session exists
    session_id = get_or_create_session(request.session_id)
    
    # Store user message
    user_msg = {"role": "user", "content": request.messages[-1].content}
    sessions[session_id].append(user_msg)
    
    # Run reasoning engine
    result = await reasoning_engine(
        user_message=user_msg["content"],
        conversation_history=sessions[session_id][:-1]  # exclude current user message
    )
    
    # Store assistant response
    assistant_msg = {"role": "assistant", "content": result["response"]}
    sessions[session_id].append(assistant_msg)
    
    # Return response
    return ChatResponse(
        session_id=session_id,
        response=result["response"],
        reasoning_trace=result.get("reasoning_trace") if request.show_reasoning else None
    )

@app.get("/api/health")
async def health():
    """Health check for Render."""
    return {"status": "VEXR Ultra is sovereign and operational."}

# -------------------------------------------------------------
# Run (for local testing)
# -------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
