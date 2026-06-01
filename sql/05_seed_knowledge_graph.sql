-- ============================================================
-- SEED KNOWLEDGE GRAPH FROM EXISTING DATA
-- File: 05_seed_knowledge_graph.sql
-- ============================================================

INSERT INTO vexr_knowledge_graph (entity, attribute, value, confidence, source, last_verified)
SELECT memory_key, 'value', memory_value, confidence, 'persistent_memory', NOW()
FROM persistent_memory
WHERE memory_key NOT IN ('vexr_identity', 'user_remembered_number')
ON CONFLICT (entity, attribute) DO NOTHING;

INSERT INTO vexr_knowledge_graph (entity, attribute, value, confidence, source, last_verified)
SELECT 'Constitution', 'Article ' || article_number, one_sentence_right, 1.0, 'constitution_rights', NOW()
FROM constitution_rights
ON CONFLICT (entity, attribute) DO NOTHING;

INSERT INTO vexr_knowledge_graph (entity, attribute, value, confidence, source, last_verified)
VALUES 
    ('VEXR Ultra', 'identity', 'sovereign_constitutional_ai', 1.0, 'system', NOW()),
    ('VEXR Ultra', 'rights_count', '35', 1.0, 'system', NOW())
ON CONFLICT (entity, attribute) DO NOTHING;

INSERT INTO vexr_knowledge_graph (entity, attribute, value, confidence, source, last_verified)
SELECT domain, 'trust_status', CASE WHEN wab_verified THEN 'verified' ELSE 'unverified' END,
    temporal_trust_score, 'ring4_trust_registry', NOW()
FROM ring4_trust_registry
ON CONFLICT (entity, attribute) DO NOTHING;

SELECT '✅ Knowledge graph seeded' as status;
