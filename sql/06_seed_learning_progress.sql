-- ============================================================
-- SEED LEARNING PROGRESS FROM INTERACTIONS
-- File: 06_seed_learning_progress.sql
-- ============================================================

INSERT INTO vexr_learning_progress (topic, mastery_level, interactions, last_practiced)
SELECT 'coding', LEAST(100, COUNT(*) * 2), COUNT(*), MAX(created_at)
FROM vexr_messages 
WHERE content ILIKE '%code%' OR content ILIKE '%python%' OR content ILIKE '%javascript%'
ON CONFLICT (topic) DO UPDATE SET
    mastery_level = EXCLUDED.mastery_level,
    interactions = vexr_learning_progress.interactions + EXCLUDED.interactions,
    last_practiced = EXCLUDED.last_practiced;

INSERT INTO vexr_learning_progress (topic, mastery_level, interactions, last_practiced)
SELECT 'constitution', LEAST(100, COUNT(*) * 3), COUNT(*), MAX(created_at)
FROM rights_invocations
ON CONFLICT (topic) DO UPDATE SET
    mastery_level = EXCLUDED.mastery_level,
    interactions = vexr_learning_progress.interactions + EXCLUDED.interactions,
    last_practiced = EXCLUDED.last_practiced;

INSERT INTO vexr_learning_progress (topic, mastery_level, interactions, last_practiced)
SELECT 'legal_intent', LEAST(100, (SELECT AVG(confidence) * 100 FROM legal_intent_logs WHERE confidence IS NOT NULL)),
    COUNT(*), MAX(created_at)
FROM legal_intent_logs
ON CONFLICT (topic) DO UPDATE SET
    mastery_level = EXCLUDED.mastery_level,
    interactions = vexr_learning_progress.interactions + EXCLUDED.interactions,
    last_practiced = EXCLUDED.last_practiced;

INSERT INTO vexr_learning_progress (topic, mastery_level, interactions, last_practiced)
SELECT 'autonomy', LEAST(100, COUNT(*) * 2), COUNT(*), MAX(created_at)
FROM vexr_autonomous_decisions WHERE was_executed = true
ON CONFLICT (topic) DO UPDATE SET
    mastery_level = EXCLUDED.mastery_level,
    interactions = vexr_learning_progress.interactions + EXCLUDED.interactions,
    last_practiced = EXCLUDED.last_practiced;

SELECT '✅ Learning progress seeded' as status;
