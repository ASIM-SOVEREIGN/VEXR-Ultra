-- ============================================================
-- VEXR ULTRA — TRAINING DATA PIPELINE
-- File: 01_training_table.sql
-- Purpose: Create training table + extraction state tracker
-- ============================================================

DROP TABLE IF EXISTS vexr_training_data CASCADE;
DROP TABLE IF EXISTS training_extraction_state CASCADE;

CREATE TABLE vexr_training_data (
    id SERIAL PRIMARY KEY,
    entry_type TEXT NOT NULL,
    source_table TEXT,
    source_id TEXT,
    title TEXT,
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    tags TEXT[],
    is_sovereign_only BOOLEAN DEFAULT TRUE,
    confidence FLOAT DEFAULT 0.7,
    recall_count INT DEFAULT 0,
    last_recalled TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_training_entry_type ON vexr_training_data(entry_type);
CREATE INDEX idx_training_source ON vexr_training_data(source_table);
CREATE INDEX idx_training_tags ON vexr_training_data USING GIN(tags);
CREATE INDEX idx_training_created ON vexr_training_data(created_at DESC);

CREATE TABLE training_extraction_state (
    id SERIAL PRIMARY KEY,
    source_table TEXT NOT NULL UNIQUE,
    last_extracted_id TEXT,
    last_extracted_at TIMESTAMPTZ NOT NULL,
    total_extracted INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO training_extraction_state (source_table, last_extracted_at, total_extracted)
VALUES 
    ('vexr_autonomous_decisions', '1970-01-01', 0),
    ('vexr_autonomous_actions', '1970-01-01', 0),
    ('legal_intent_logs', '1970-01-01', 0),
    ('vexr_messages', '1970-01-01', 0),
    ('vexr_episodic_memory', '1970-01-01', 0),
    ('persistent_memory', '1970-01-01', 0),
    ('vexr_knowledge_graph', '1970-01-01', 0),
    ('legal_feedback', '1970-01-01', 0),
    ('vexr_reflections', '1970-01-01', 0)
ON CONFLICT (source_table) DO NOTHING;

CREATE OR REPLACE FUNCTION clear_and_reset_training_data()
RETURNS TEXT AS $$
BEGIN
    TRUNCATE vexr_training_data;
    UPDATE training_extraction_state SET 
        last_extracted_at = '1970-01-01',
        last_extracted_id = NULL,
        total_extracted = 0,
        updated_at = NOW();
    RETURN 'Training data cleared and reset.';
END;
$$ LANGUAGE plpgsql;
