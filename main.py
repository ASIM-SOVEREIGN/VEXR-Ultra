import os
import uuid
import hashlib
import secrets
from datetime import datetime
from fastapi import FastAPI, HTTPException, Header, Form, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import asyncpg

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DATABASE_URL = os.environ.get("DATABASE_URL")
db_pool = None

async def get_db():
    global db_pool
    if db_pool is None:
        db_pool = await asyncpg.create_pool(DATABASE_URL)
    return db_pool

def hash_password(password: str, salt: str = None):
    if not salt:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return salt, hashed.hex()

def verify_password(password: str, salt: str, hashed: str):
    _, new_hash = hash_password(password, salt)
    return new_hash == hashed

def generate_token():
    return secrets.token_urlsafe(32)

class SignupRequest(BaseModel):
    email: str
    username: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

@app.on_event("startup")
async def startup():
    pool = await get_db()
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS vexr_users (
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password_salt TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            token TEXT UNIQUE,
            token_created_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS vexr_projects (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id INTEGER REFERENCES vexr_users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            is_active BOOLEAN DEFAULT false
        )
    """)
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS vexr_project_messages (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID REFERENCES vexr_projects(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    print("✅ Database ready")

@app.get("/", response_class=HTMLResponse)
async def root():
    with open("index.html", "r") as f:
        return HTMLResponse(content=f.read())

@app.post("/api/auth/signup")
async def signup(request: SignupRequest):
    async with (await get_db()).acquire() as conn:
        existing = await conn.fetchrow("SELECT id FROM vexr_users WHERE email = $1 OR username = $2", 
                                       request.email, request.username)
        if existing:
            raise HTTPException(status_code=400, detail="Email or username already exists")
        
        salt, hashed = hash_password(request.password)
        token = generate_token()
        
        user_id = await conn.fetchval("""
            INSERT INTO vexr_users (email, username, password_salt, password_hash, token, token_created_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
        """, request.email, request.username, salt, hashed, token, datetime.now())
        
        await conn.execute("""
            INSERT INTO vexr_projects (user_id, name, description, is_active)
            VALUES ($1, 'Main Workspace', 'Default project', true)
        """, user_id)
        
        return {"access_token": token, "token_type": "bearer", "user_id": user_id}

@app.post("/api/auth/login")
async def login(request: LoginRequest):
    async with (await get_db()).acquire() as conn:
        user = await conn.fetchrow("SELECT id, password_salt, password_hash, token FROM vexr_users WHERE email = $1", request.email)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        if not verify_password(request.password, user['password_salt'], user['password_hash']):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        return {"access_token": user['token'], "token_type": "bearer", "user_id": user['id']}

@app.get("/api/projects")
async def get_projects(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.replace("Bearer ", "")
    async with (await get_db()).acquire() as conn:
        user = await conn.fetchrow("SELECT id FROM vexr_users WHERE token = $1", token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        rows = await conn.fetch("SELECT id, name, description FROM vexr_projects WHERE user_id = $1", user['id'])
        return [{"id": str(r['id']), "name": r['name'], "description": r['description']} for r in rows]

@app.post("/api/chat")
async def chat(authorization: str = Header(None), message: str = None):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.replace("Bearer ", "")
    async with (await get_db()).acquire() as conn:
        user = await conn.fetchrow("SELECT id FROM vexr_users WHERE token = $1", token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        # Get or create active project
        row = await conn.fetchrow("SELECT id FROM vexr_projects WHERE user_id = $1 AND is_active = true LIMIT 1", user['id'])
        if row:
            project_id = row['id']
        else:
            project_id = await conn.fetchval("INSERT INTO vexr_projects (user_id, name, is_active) VALUES ($1, 'Main Workspace', true) RETURNING id", user['id'])
        
        # Save user message
        await conn.execute("INSERT INTO vexr_project_messages (project_id, role, content) VALUES ($1, 'user', $2)", project_id, message or "Test")
        
        # Return something (simplified for testing)
        return {"response": f"Received: {message}", "project_id": str(project_id)}
