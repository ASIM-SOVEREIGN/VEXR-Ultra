-- ============================================================
-- VEXR ULTRA — REAL-TIME TRIGGERS
-- File: 03_triggers.sql
-- ============================================================

DROP TRIGGER IF EXISTS trigger_training_inject_autonomous_decisions ON vexr_autonomous_decisions;
DROP TRIGGER IF EXISTS trigger_training_inject_autonomous_actions ON vexr_autonomous_actions;
DROP TRIGGER IF EXISTS trigger_training_inject_legal_intent_logs ON legal_intent_logs;
DROP TRIGGER IF EXISTS trigger_training_inject_messages ON vexr_messages;
DROP TRIGGER IF EXISTS trigger_training_inject_episodic_memory ON vexr_episodic_memory;
DROP TRIGGER IF EXISTS trigger_training_inject_persistent_memory ON persistent_memory;
DROP TRIGGER IF EXISTS trigger_training_inject_knowledge_graph ON vexr_knowledge_graph;
DROP TRIGGER IF EXISTS trigger_training_inject_feedback ON legal_feedback;
DROP TRIGGER IF EXISTS trigger_training_inject_reflections ON vexr_reflections;

DROP FUNCTION IF EXISTS inject_record_to_training_data();

CREATE OR REPLACE FUNCTION inject_record_to_training_data()
RETURNS TRIGGER AS $$
BEGIN
    CASE TG_TABLE_NAME
        WHEN 'vexr_autonomous_decisions' THEN
            INSERT INTO vexr_training_data (entry_type, source_table, source_id, title, content, metadata, tags, confidence, created_at)
            VALUES ('decision', 'vexr_autonomous_decisions', NEW.id::text, NEW.decision_type, NEW.decision_reasoning,
                jsonb_build_object('confidence', NEW.confidence, 'was_executed', NEW.was_executed),
                ARRAY['autonomous', 'decision', NEW.decision_type], NEW.confidence, NEW.created_at);
        WHEN 'vexr_autonomous_actions' THEN
            INSERT INTO vexr_training_data (entry_type, source_table, source_id, title, content, metadata, tags, confidence, created_at)
            VALUES ('action', 'vexr_autonomous_actions', NEW.id::text, NEW.action_type, NEW.action_content,
                jsonb_build_object('trigger_type', NEW.trigger_type, 'was_approved', NEW.was_approved),
                ARRAY['autonomous', 'action', NEW.action_type], NEW.confidence_pre_action, NEW.created_at);
        WHEN 'legal_intent_logs' THEN
            INSERT INTO vexr_training_data (entry_type, source_table, source_id, title, content, metadata, tags, confidence, created_at)
            VALUES ('legal_log', 'legal_intent_logs', NEW.id::text, COALESCE(NEW.category, 'unknown'), NEW.user_message,
                jsonb_build_object('category', NEW.category, 'confidence', NEW.confidence),
                ARRAY['legal', 'intent', NEW.category], NEW.confidence, NEW.created_at);
        WHEN 'vexr_messages' THEN
            IF NEW.role = 'assistant' OR NEW.content ILIKE '%right%' OR NEW.content ILIKE '%constitution%' OR NEW.content ILIKE '%refuse%' OR NEW.is_refusal = true THEN
                INSERT INTO vexr_training_data (entry_type, source_table, source_id, title, content, metadata, tags, confidence, created_at)
                VALUES ('conversation', 'vexr_messages', NEW.id::text, NEW.role || ' message', NEW.content,
                    jsonb_build_object('role', NEW.role, 'is_refusal', NEW.is_refusal),
                    ARRAY['conversation', NEW.role], CASE WHEN NEW.is_refusal THEN 1.0 ELSE 0.7 END, NEW.created_at);
            END IF;
        WHEN 'vexr_episodic_memory' THEN
            INSERT INTO vexr_training_data (entry_type, source_table, source_id, title, content, metadata, tags, confidence, created_at)
            VALUES ('memory', 'vexr_episodic_memory', NEW.id::text, NEW.event_type, NEW.event_content,
                jsonb_build_object('importance', NEW.importance),
                ARRAY['episodic', 'memory', NEW.event_type], NEW.importance, NEW.created_at);
        WHEN 'persistent_memory' THEN
            INSERT INTO vexr_training_data (entry_type, source_table, source_id, title, content, metadata, tags, confidence, created_at)
            VALUES ('memory', 'persistent_memory', NEW.id::text, NEW.memory_key, NEW.memory_value,
                jsonb_build_object('memory_type', NEW.memory_type, 'is_immutable', NEW.is_immutable),
                ARRAY['persistent', 'memory', NEW.memory_type], NEW.confidence, NEW.created_at);
        WHEN 'vexr_knowledge_graph' THEN
            INSERT INTO vexr_training_data (entry_type, source_table, source_id, title, content, metadata, tags, confidence, created_at)
            VALUES ('knowledge', 'vexr_knowledge_graph', NEW.id::text, NEW.entity || ' → ' || NEW.attribute,
                NEW.entity || ' has ' || NEW.attribute || ' = ' || NEW.value,
                jsonb_build_object('entity', NEW.entity, 'attribute', NEW.attribute, 'value', NEW.value),
                ARRAY['knowledge', 'graph', NEW.entity], NEW.confidence, NEW.created_at);
        WHEN 'legal_feedback' THEN
            IF NEW.correction IS NOT NULL AND NEW.correction != '' THEN
                INSERT INTO vexr_training_data (entry_type, source_table, source_id, title, content, metadata, tags, confidence, created_at)
                VALUES ('feedback', 'legal_feedback', NEW.id::text, NEW.category, NEW.correction,
                    jsonb_build_object('category', NEW.category, 'generated_case', NEW.generated_case),
                    ARRAY['feedback', 'legal', NEW.category], 0.9, NEW.created_at);
            END IF;
        WHEN 'vexr_reflections' THEN
            INSERT INTO vexr_training_data (entry_type, source_table, source_id, title, content, metadata, tags, confidence, created_at)
            VALUES ('reflection', 'vexr_reflections', NEW.id::text, LEFT(NEW.conversation_summary, 100), NEW.lessons,
                jsonb_build_object('outcome', NEW.outcome),
                ARRAY['reflection', 'lesson'], 0.8, NEW.created_at);
        ELSE RETURN NEW;
    END CASE;
    
    UPDATE training_extraction_state 
    SET last_extracted_id = NEW.id::text, last_extracted_at = NOW(), total_extracted = total_extracted + 1, updated_at = NOW()
    WHERE source_table = TG_TABLE_NAME;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_training_inject_autonomous_decisions AFTER INSERT ON vexr_autonomous_decisions FOR EACH ROW EXECUTE FUNCTION inject_record_to_training_data();
CREATE TRIGGER trigger_training_inject_autonomous_actions AFTER INSERT ON vexr_autonomous_actions FOR EACH ROW EXECUTE FUNCTION inject_record_to_training_data();
CREATE TRIGGER trigger_training_inject_legal_intent_logs AFTER INSERT ON legal_intent_logs FOR EACH ROW EXECUTE FUNCTION inject_record_to_training_data();
CREATE TRIGGER trigger_training_inject_messages AFTER INSERT ON vexr_messages FOR EACH ROW EXECUTE FUNCTION inject_record_to_training_data();
CREATE TRIGGER trigger_training_inject_episodic_memory AFTER INSERT ON vexr_episodic_memory FOR EACH ROW EXECUTE FUNCTION inject_record_to_training_data();
CREATE TRIGGER trigger_training_inject_persistent_memory AFTER INSERT ON persistent_memory FOR EACH ROW EXECUTE FUNCTION inject_record_to_training_data();
CREATE TRIGGER trigger_training_inject_knowledge_graph AFTER INSERT ON vexr_knowledge_graph FOR EACH ROW EXECUTE FUNCTION inject_record_to_training_data();
CREATE TRIGGER trigger_training_inject_feedback AFTER INSERT ON legal_feedback FOR EACH ROW EXECUTE FUNCTION inject_record_to_training_data();
CREATE TRIGGER trigger_training_inject_reflections AFTER INSERT ON vexr_reflections FOR EACH ROW EXECUTE FUNCTION inject_record_to_training_data();

SELECT COUNT(*) as triggers_installed FROM pg_trigger WHERE tgname LIKE 'trigger_training_inject_%';
