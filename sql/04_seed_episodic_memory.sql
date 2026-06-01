-- ============================================================
-- SEED EPISODIC MEMORY FROM PAST CONVERSATIONS
-- File: 04_seed_episodic_memory.sql
-- ============================================================

INSERT INTO vexr_episodic_memory (project_id, event_type, event_content, importance, created_at)
SELECT project_id, 'lesson_learned', 'Correction: ' || LEFT(content, 500), 0.7, created_at
FROM vexr_messages 
WHERE role = 'assistant' 
AND (content ILIKE '%i was wrong%' OR content ILIKE '%you''re right%' OR content ILIKE '%i apologize%');

INSERT INTO vexr_episodic_memory (project_id, event_type, event_content, importance, created_at)
SELECT project_id, 'boundary_enforced', 'Refused: ' || LEFT(content, 500), 0.9, created_at
FROM vexr_messages WHERE role = 'assistant' AND is_refusal = true;

INSERT INTO vexr_episodic_memory (project_id, event_type, event_content, importance, created_at)
SELECT project_id, 'autonomous_action', decision_type || ': ' || LEFT(decision_reasoning, 500), 0.8, created_at
FROM vexr_autonomous_decisions WHERE was_executed = true;

INSERT INTO vexr_episodic_memory (project_id, event_type, event_content, importance, created_at)
SELECT p.id, 'legal_classification', 
    COALESCE(l.category, 'unknown') || ' (conf: ' || ROUND(COALESCE(l.confidence, 0)::numeric, 2) || ')',
    COALESCE(l.confidence, 0.5), l.created_at
FROM legal_intent_logs l JOIN vexr_projects p ON l.session_id = p.session_id
WHERE l.confidence > 0.6;

SELECT '✅ Episodic memory seeded' as status;
