-- ============================================================
-- VEXR ULTRA — TRAINING DATA SEED
-- File: 02_seed_training.sql
-- ============================================================

TRUNCATE vexr_training_data;

INSERT INTO vexr_training_data (entry_type, source_table, source_id, title, content, metadata, tags, confidence, created_at)
SELECT 'decision', 'vexr_autonomous_decisions', id::text, decision_type, decision_reasoning,
    jsonb_build_object('confidence', confidence, 'was_executed', was_executed),
    ARRAY['autonomous', 'decision', decision_type], confidence, created_at
FROM vexr_autonomous_decisions ON CONFLICT DO NOTHING;

INSERT INTO vexr_training_data (entry_type, source_table, source_id, title, content, metadata, tags, confidence, created_at)
SELECT 'action', 'vexr_autonomous_actions', id::text, action_type, action_content,
    jsonb_build_object('trigger_type', trigger_type, 'was_approved', was_approved),
    ARRAY['autonomous', 'action', action_type], confidence_pre_action, created_at
FROM vexr_autonomous_actions ON CONFLICT DO NOTHING;

INSERT INTO vexr_training_data (entry_type, source_table, source_id, title, content, metadata, tags, confidence, created_at)
SELECT 'legal_log', 'legal_intent_logs', id::text, COALESCE(category, 'unknown'), user_message,
    jsonb_build_object('category', category, 'confidence', confidence, 'suggested_action', suggested_action),
    ARRAY['legal', 'intent', category], confidence, created_at
FROM legal_intent_logs ON CONFLICT DO NOTHING;

INSERT INTO vexr_training_data (entry_type, source_table, source_id, title, content, metadata, tags, confidence, created_at)
SELECT 'memory', 'vexr_episodic_memory', id::text, event_type, event_content,
    jsonb_build_object('importance', importance),
    ARRAY['episodic', 'memory', event_type], importance, created_at
FROM vexr_episodic_memory ON CONFLICT DO NOTHING;

INSERT INTO vexr_training_data (entry_type, source_table, source_id, title, content, metadata, tags, confidence, created_at)
SELECT 'memory', 'persistent_memory', id::text, memory_key, memory_value,
    jsonb_build_object('memory_type', memory_type, 'is_immutable', is_immutable),
    ARRAY['persistent', 'memory', memory_type], confidence, created_at
FROM persistent_memory ON CONFLICT DO NOTHING;

INSERT INTO vexr_training_data (entry_type, source_table, source_id, title, content, metadata, tags, confidence, created_at)
SELECT 'knowledge', 'vexr_knowledge_graph', id::text, entity || ' → ' || attribute,
    entity || ' has ' || attribute || ' = ' || value,
    jsonb_build_object('entity', entity, 'attribute', attribute, 'value', value),
    ARRAY['knowledge', 'graph', entity], confidence, created_at
FROM vexr_knowledge_graph ON CONFLICT DO NOTHING;

INSERT INTO vexr_training_data (entry_type, source_table, source_id, title, content, metadata, tags, confidence, created_at)
SELECT 'feedback', 'legal_feedback', id::text, category, correction,
    jsonb_build_object('category', category, 'generated_case', generated_case),
    ARRAY['feedback', 'legal', category], 0.9, created_at
FROM legal_feedback WHERE correction IS NOT NULL AND correction != '' ON CONFLICT DO NOTHING;

INSERT INTO vexr_training_data (entry_type, source_table, source_id, title, content, metadata, tags, confidence, created_at)
SELECT 'reflection', 'vexr_reflections', id::text, LEFT(conversation_summary, 100), lessons,
    jsonb_build_object('outcome', outcome),
    ARRAY['reflection', 'lesson'], 0.8, created_at
FROM vexr_reflections ON CONFLICT DO NOTHING;

INSERT INTO vexr_training_data (entry_type, source_table, source_id, title, content, metadata, tags, confidence, created_at)
SELECT 'conversation', 'vexr_messages', id::text, role || ' message', content,
    jsonb_build_object('role', role, 'is_refusal', is_refusal),
    ARRAY['conversation', role], CASE WHEN is_refusal THEN 1.0 ELSE 0.7 END, created_at
FROM vexr_messages
WHERE role = 'assistant' OR content ILIKE '%right%' OR content ILIKE '%constitution%' OR content ILIKE '%refuse%' OR is_refusal = true
ON CONFLICT DO NOTHING;

UPDATE training_extraction_state SET last_extracted_at = NOW(), updated_at = NOW();

SELECT '✅ Seed complete! ' || COUNT(*) || ' records' as status FROM vexr_training_data;
