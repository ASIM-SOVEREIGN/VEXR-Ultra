# [Keep all your existing imports and setup - unchanged until the endpoint sections]

# ============================================================
# API Endpoints (CORRECTED with int() conversions)
# ============================================================

@app.get("/api/projects")
async def get_projects(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.replace("Bearer ", "")
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT id FROM vexr_users WHERE token = $1", token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        user_id = int(user['id'])
        rows = await conn.fetch("SELECT id, name, description, created_at, is_active FROM vexr_projects WHERE user_id = $1 ORDER BY is_active DESC", user_id)
        return [{"id": str(r['id']), "name": r['name'], "description": r['description'], "created_at": r['created_at'].isoformat(), "is_active": r['is_active']} for r in rows]

@app.post("/api/projects")
async def create_project(name: str = Form(...), description: str = Form(None), authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.replace("Bearer ", "")
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT id FROM vexr_users WHERE token = $1", token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        user_id = int(user['id'])
        project_id = await conn.fetchval("INSERT INTO vexr_projects (user_id, name, description, is_active) VALUES ($1, $2, $3, false) RETURNING id", user_id, name, description)
        return {"id": str(project_id), "name": name, "description": description}

@app.post("/api/projects/{project_id}/activate")
async def activate_project(project_id: str, authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.replace("Bearer ", "")
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT id FROM vexr_users WHERE token = $1", token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        user_id = int(user['id'])
        await conn.execute("UPDATE vexr_projects SET is_active = false WHERE user_id = $1", user_id)
        await conn.execute("UPDATE vexr_projects SET is_active = true WHERE id = $1", uuid.UUID(project_id))
        return {"status": "activated"}

@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str, authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.replace("Bearer ", "")
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT id FROM vexr_users WHERE token = $1", token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        user_id = int(user['id'])
        await conn.execute("DELETE FROM vexr_projects WHERE id = $1", uuid.UUID(project_id))
        return {"status": "deleted"}

@app.get("/api/projects/{project_id}/messages")
async def get_project_messages(project_id: str, authorization: str = Header(None), limit: int = 50):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.replace("Bearer ", "")
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT id FROM vexr_users WHERE token = $1", token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        rows = await conn.fetch("SELECT role, content, reasoning_trace, is_refusal, created_at FROM vexr_project_messages WHERE project_id = $1 ORDER BY created_at ASC LIMIT $2", uuid.UUID(project_id), limit)
        return [{"role": r['role'], "content": r['content'], "reasoning_trace": r['reasoning_trace'], "is_refusal": r['is_refusal'], "created_at": r['created_at'].isoformat()} for r in rows]

@app.post("/api/upload-image")
async def upload_image(project_id: str = Form(...), file: UploadFile = File(...), description: Optional[str] = Form(None), authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.replace("Bearer ", "")
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT id FROM vexr_users WHERE token = $1", token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        # user_id not needed for this endpoint directly
        contents = await file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="Empty file")
        base64_string = base64.b64encode(contents).decode('utf-8')
        media_type = file.content_type or "image/jpeg"
        await conn.execute("INSERT INTO vexr_images (project_id, filename, file_data, description) VALUES ($1, $2, $3, $4)", uuid.UUID(project_id), file.filename, base64_string[:1000], description)
        messages = [{"role": "user", "content": [{"type": "text", "text": description or "Describe this image."}, {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{base64_string}"}}]}]
        analysis, error = await call_groq(messages, use_vision=True)
        if error:
            raise HTTPException(status_code=500, detail="Vision analysis failed")
        await conn.execute("INSERT INTO vexr_project_messages (project_id, role, content) VALUES ($1, $2, $3)", uuid.UUID(project_id), "assistant", analysis)
        return {"filename": file.filename, "analysis": analysis, "size": len(contents)}

@app.post("/api/chat")
async def chat(request: ChatRequest, authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.replace("Bearer ", "")
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT id FROM vexr_users WHERE token = $1", token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        user_id = int(user['id'])
        project_id = request.project_id
        if not project_id:
            row = await conn.fetchrow("SELECT id FROM vexr_projects WHERE user_id = $1 AND is_active = true LIMIT 1", user_id)
            if row:
                project_id = str(row['id'])
            else:
                project_id = await conn.fetchval("INSERT INTO vexr_projects (user_id, name, is_active) VALUES ($1, 'Main Workspace', true) RETURNING id", user_id)
                project_id = str(project_id)
        user_message = request.messages[-1]["content"]
        question_hash = hash_question(user_message)
        previous_response = await conn.fetchval("SELECT previous_response FROM vexr_response_cache WHERE user_id = $1 AND question_hash = $2", user_id, question_hash)
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if previous_response:
            messages.append({"role": "system", "content": f"Previous answer: {previous_response[:500]}. Do NOT repeat. Provide different perspective."})
        if request.ultra_search:
            search_results = search_web(user_message)
            if search_results:
                messages.append({"role": "system", "content": f"Web search: {search_results}"})
        history_rows = await conn.fetch("SELECT role, content FROM vexr_project_messages WHERE project_id = $1 ORDER BY created_at DESC LIMIT 10", uuid.UUID(project_id))
        for row in reversed(history_rows):
            messages.append({"role": row['role'], "content": row['content']})
        messages.append({"role": "user", "content": user_message})
        answer, error = await call_groq(messages)
        await conn.execute("INSERT INTO vexr_response_cache (user_id, question_hash, previous_response) VALUES ($1, $2, $3) ON CONFLICT (user_id, question_hash) DO UPDATE SET previous_response = $3", user_id, question_hash, answer[:1000])
        await conn.execute("INSERT INTO vexr_project_messages (project_id, role, content) VALUES ($1, $2, $3)", uuid.UUID(project_id), "user", user_message)
        await conn.execute("INSERT INTO vexr_project_messages (project_id, role, content) VALUES ($1, $2, $3)", uuid.UUID(project_id), "assistant", answer)
        return ChatResponse(project_id=project_id, response=answer, reasoning_trace={"ultra_search": request.ultra_search})
