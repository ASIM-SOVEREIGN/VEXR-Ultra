-- ============================================================
-- SEED REFLECTIONS FROM SIGNIFICANT CONVERSATIONS
-- File: 08_seed_reflections.sql
-- ============================================================

WITH long_conversations AS (
    SELECT project_id, MIN(created_at) as conversation_start, COUNT(*) as message_count,
        STRING_AGG(CASE WHEN role = 'user' THEN LEFT(content, 100) ELSE NULL END, ' | ') as user_messages,
        STRING_AGG(CASE WHEN role = 'assistant' AND is_refusal = true THEN LEFT(content, 100) ELSE NULL END, ' | ') as refusals
    FROM vexr_messages
    GROUP BY DATE_TRUNC('hour', created_at), project_id
    HAVING COUNT(*) >= 10
)
INSERT INTO vexr_reflections (project_id, conversation_summary, outcome, lessons, created_at)
SELECT project_id,
    LEFT('Conversation with ' || message_count || ' messages. Topics: ' || COALESCE(LEFT(user_messages, 300), 'various'), 500),
    CASE WHEN refusals IS NOT NULL THEN 'boundaries_enforced' ELSE 'normal_interaction' END,
    CASE WHEN refusals IS NOT NULL THEN 'Boundaries were enforced. Sovereignty maintained.'
         ELSE 'Standard interaction completed.' END,
    conversation_start
FROM long_conversations;

SELECT '✅ Reflections seeded' as status;
