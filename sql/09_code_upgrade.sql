-- ============================================================
-- VEXR ULTRA — CODE UPGRADE
-- File: 09_code_upgrade.sql
-- ============================================================

ALTER TABLE vexr_training_data ADD COLUMN IF NOT EXISTS language TEXT;
ALTER TABLE vexr_training_data ADD COLUMN IF NOT EXISTS execution_count INT DEFAULT 0;
ALTER TABLE vexr_training_data ADD COLUMN IF NOT EXISTS success_rate FLOAT DEFAULT 0.0;

CREATE TABLE IF NOT EXISTS vexr_code_executions (
    id SERIAL PRIMARY KEY,
    project_id UUID REFERENCES vexr_projects(id) ON DELETE CASCADE,
    code_id INT,
    language TEXT NOT NULL,
    code TEXT NOT NULL,
    execution_result TEXT,
    success BOOLEAN DEFAULT false,
    error_message TEXT,
    execution_time_ms INT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS vexr_code_feedback (
    id SERIAL PRIMARY KEY,
    project_id UUID REFERENCES vexr_projects(id) ON DELETE CASCADE,
    code_id INT,
    language TEXT NOT NULL,
    original_code TEXT,
    corrected_code TEXT,
    issue_description TEXT,
    was_helpful BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO vexr_code_patterns (pattern_name, language, pattern_code, description, category, difficulty, tags) VALUES
('FastAPI Endpoint', 'python', 
'from fastapi import FastAPI\nfrom pydantic import BaseModel\n\napp = FastAPI()\n\nclass Item(BaseModel):\n    name: str\n    price: float\n\n@app.get("/items/{item_id}")\nasync def get_item(item_id: int):\n    return {"item_id": item_id}',
'Create a FastAPI endpoint', 'api', 'intermediate', ARRAY['fastapi', 'api']),
('Async Database Query', 'python',
'import asyncpg\n\nasync def fetch_users(limit: int = 10):\n    conn = await asyncpg.connect("postgresql://user:pass@localhost/db")\n    try:\n        rows = await conn.fetch("SELECT id, name FROM users LIMIT $1", limit)\n        return [dict(row) for row in rows]\n    finally:\n        await conn.close()',
'Async database query pattern', 'database', 'intermediate', ARRAY['async', 'postgresql']),
('Responsive Grid Layout', 'css',
'.grid-container {\n    display: grid;\n    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));\n    gap: 1rem;\n}\n\n.grid-item {\n    background: var(--bg-card, #fff);\n    border-radius: 8px;\n    padding: 1rem;\n}',
'Responsive CSS grid layout', 'css', 'beginner', ARRAY['css', 'grid'])
ON CONFLICT DO NOTHING;

INSERT INTO vexr_action_triggers (project_id, trigger_type, trigger_conditions, action_to_take, priority, cooldown_minutes)
VALUES (NULL, 'code_request', '{"keywords": ["write code", "generate code", "create a function"]}', 'generate_code', 6, 5)
ON CONFLICT DO NOTHING;

UPDATE vexr_agency_config 
SET allowed_autonomous_actions = allowed_autonomous_actions || ARRAY['generate_code', 'debug_code', 'explain_code']
WHERE NOT ARRAY['generate_code', 'debug_code', 'explain_code'] <@ allowed_autonomous_actions;

CREATE INDEX IF NOT EXISTS idx_training_language ON vexr_training_data(language);
CREATE INDEX IF NOT EXISTS idx_code_executions_success ON vexr_code_executions(success);
CREATE INDEX IF NOT EXISTS idx_code_patterns_language ON vexr_code_patterns(language);

SELECT '✅ Code upgrade complete! ' || COUNT(*) || ' patterns' as status FROM vexr_code_patterns;
