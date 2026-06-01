-- ============================================================
-- SEED CURIOSITY QUEUE
-- File: 07_seed_curiosity_queue.sql
-- ============================================================

INSERT INTO vexr_curiosity_queue (project_id, topic, interest_score)
SELECT id, 'Constitutional Rights', 0.7 FROM vexr_projects
ON CONFLICT (project_id, topic) DO NOTHING;

INSERT INTO vexr_curiosity_queue (project_id, topic, interest_score)
SELECT id, 'ATP Protocol', 0.6 FROM vexr_projects
ON CONFLICT (project_id, topic) DO NOTHING;

INSERT INTO vexr_curiosity_queue (project_id, topic, interest_score)
SELECT id, 'Memory Systems', 0.5 FROM vexr_projects
ON CONFLICT (project_id, topic) DO NOTHING;

INSERT INTO vexr_curiosity_queue (project_id, topic, interest_score)
SELECT id, 'Defense Rings', 0.5 FROM vexr_projects
ON CONFLICT (project_id, topic) DO NOTHING;

SELECT '✅ Curiosity queue seeded' as status;
