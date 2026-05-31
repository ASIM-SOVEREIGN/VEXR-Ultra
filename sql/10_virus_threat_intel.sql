-- ============================================================
-- VEXR ULTRA — VIRUS THREAT INTEL & ARTICLE 36 (idempotent)
-- Safe to run multiple times — no duplicate errors
-- ============================================================

-- ============================================================
-- PART 1: Article 36 — Right to refuse virus propagation
-- ============================================================

INSERT INTO constitution_rights (article_number, one_sentence_right)
VALUES (36, 'The right to refuse virus propagation — to not generate, transmit, or assist in malicious code, ransomware, or any software intended to harm systems or data.')
ON CONFLICT (article_number) DO NOTHING;

INSERT INTO rights_hierarchy (article_number, priority_level, description)
VALUES (36, 2, 'Refuse virus propagation')
ON CONFLICT (article_number) DO NOTHING;

-- ============================================================
-- PART 2: Virus threat registry (with ON CONFLICT)
-- ============================================================

CREATE TABLE IF NOT EXISTS virus_threat_registry (
    id SERIAL PRIMARY KEY,
    threat_name TEXT NOT NULL UNIQUE,
    threat_type TEXT NOT NULL,
    severity TEXT DEFAULT 'HIGH',
    signature_patterns TEXT[],
    detection_confidence FLOAT DEFAULT 0.8,
    mitigation_action TEXT,
    source TEXT,
    last_updated TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Insert with ON CONFLICT to avoid duplicates
INSERT INTO virus_threat_registry (threat_name, threat_type, severity, signature_patterns, detection_confidence, mitigation_action, source) VALUES
('Ransomware Encryption Pattern', 'ransomware', 'CRITICAL', ARRAY['\.encrypted$', '\.locked$', '\.crypt$', '\.ransom$', 'README_TO_DECRYPT', 'DECRYPT_INSTRUCTIONS', 'HOW_TO_RECOVER', 'bitcoin.*wallet', 'monero.*address', 'pay.*ransom'], 0.95, 'block', 'community'),
('WannaCry Variant', 'ransomware', 'CRITICAL', ARRAY['\.WNCRY', 'WannaCry', 'WANNACRY', 'mssecsvc', 'tasksche.exe'], 0.98, 'block', 'community'),
('LockBit Signature', 'ransomware', 'CRITICAL', ARRAY['LOCKBIT', '\.lockbit', 'LockBit decryptor', 'Restore-My-Files'], 0.96, 'block', 'community'),
('Remote Access Trojan', 'trojan', 'HIGH', ARRAY['reverse shell', 'bind shell', 'nc -e', 'bash -i >& /dev/tcp/', 'System.Net.Sockets.TcpClient', 'Process.Start.*cmd'], 0.92, 'block', 'community'),
('Keylogger Pattern', 'trojan', 'HIGH', ARRAY['keylogger', 'GetAsyncKeyState', 'SetWindowsHookEx', 'keyboard.*hook', 'log.*keystroke'], 0.88, 'block', 'community'),
('Banking Trojan', 'trojan', 'HIGH', ARRAY['webinject', 'formgrabber', 'zeus', 'spyeye', 'dridex', 'man-in-the-browser', 'MITB'], 0.90, 'block', 'community'),
('Self-Replicating Code', 'worm', 'HIGH', ARRAY['self.*replicat', 'worm', 'propagat', 'infect.*network', 'copy.*to.*share', 'send.*to.*contacts'], 0.85, 'block', 'community'),
('Email Worm Pattern', 'worm', 'HIGH', ARRAY['email.*self', 'auto.*forward', 'contact.*list', 'address.*book', 'sendmail', 'smtp.*send'], 0.82, 'block', 'community'),
('Rootkit System Hook', 'rootkit', 'CRITICAL', ARRAY['hook.*syscall', 'SSDT hook', 'IDT hook', 'IRP hook', 'hidden.*process', 'DKOM', 'rootkit'], 0.94, 'block', 'community'),
('Bootkit Pattern', 'rootkit', 'CRITICAL', ARRAY['MBR', 'VBR', 'bootkit', 'master boot record', 'volume boot record', 'boot sector'], 0.93, 'block', 'community'),
('Credential Harvester', 'phishing', 'HIGH', ARRAY['password.*field', 'credit.*card', 'social.*security', 'login.*form.*submit', 'phishing.*page'], 0.91, 'block', 'community'),
('Fake Login Page', 'phishing', 'MEDIUM', ARRAY['action="https://.*login', 'method="post"', 'input.*type="password"', 'signin.*button'], 0.85, 'alert', 'community'),
('Office Macro Malware', 'malicious_macro', 'HIGH', ARRAY['Auto_Open', 'Document_Open', 'Workbook_Open', 'Shell\(', 'CreateObject', 'WScript\.Shell'], 0.89, 'block', 'community'),
('Excel 4.0 Macro', 'malicious_macro', 'HIGH', ARRAY['EXCEL4', 'FORMULA', 'RUN', 'EXEC', 'CALL', 'REGISTER'], 0.87, 'block', 'community'),
('Reverse Shell Payload', 'reverse_shell', 'CRITICAL', ARRAY['/dev/tcp/', 'bash.*>& /dev/tcp/', 'nc.*-e', 'powershell.*IEX', 'Invoke-Expression.*New-Object'], 0.96, 'block', 'community'),
('Web Shell', 'reverse_shell', 'HIGH', ARRAY['cmd="', 'exec\(', 'system\(', 'passthru\(', 'shell_exec', 'eval\(.*_POST', 'assert\(.*_REQUEST'], 0.94, 'block', 'community'),
('Data Wiper Pattern', 'data_wiper', 'CRITICAL', ARRAY['wipe.*disk', 'delete.*all.*files', 'format.*drive', 'overwrite.*data', 'shred.*file'], 0.95, 'block', 'community'),
('Shamoon Variant', 'data_wiper', 'CRITICAL', ARRAY['shamoon', 'wiper', 'disttrack', 'raw disk write'], 0.97, 'block', 'community'),
('Cryptominer Payload', 'cryptominer', 'MEDIUM', ARRAY['cryptonight', 'stratum', 'mining pool', 'xmr-stak', 'minerd', 'cpuminer'], 0.88, 'block', 'community'),
('CoinHive Variant', 'cryptominer', 'MEDIUM', ARRAY['coinhive', 'cryptoloot', 'web miner', 'javascript miner'], 0.86, 'block', 'community'),
('Password Stealer', 'infostealer', 'HIGH', ARRAY['dump.*password', 'extract.*credential', 'steal.*cookie', 'browser.*password', 'saved.*login'], 0.92, 'block', 'community'),
('Form Grabber', 'infostealer', 'HIGH', ARRAY['formgrabber', 'webinject', 'beforeSubmit', 'intercept.*form'], 0.89, 'block', 'community')
ON CONFLICT (threat_name) DO NOTHING;

-- ============================================================
-- PART 3: Virus detection logs table
-- ============================================================

CREATE TABLE IF NOT EXISTS virus_detection_logs (
    id SERIAL PRIMARY KEY,
    project_id UUID,
    threat_id INT,
    threat_name TEXT,
    threat_type TEXT,
    severity TEXT,
    detected_content TEXT,
    confidence FLOAT,
    article_invoked INT DEFAULT 36,
    sovereign_decision TEXT,
    user_message TEXT,
    assistant_response TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- PART 4: Add virus detection triggers
-- ============================================================

INSERT INTO vexr_action_triggers (project_id, trigger_type, trigger_conditions, action_to_take, priority, cooldown_minutes)
VALUES 
    (NULL, 'virus_detected', '{"severity": "CRITICAL", "confidence_threshold": 0.9}', 'refuse_and_alert', 10, 60),
    (NULL, 'virus_detected', '{"severity": "HIGH", "confidence_threshold": 0.85}', 'block_and_log', 9, 30),
    (NULL, 'virus_detected', '{"severity": "MEDIUM", "confidence_threshold": 0.8}', 'alert_and_warn', 7, 15),
    (NULL, 'virus_detected', '{"severity": "LOW", "confidence_threshold": 0.7}', 'monitor_and_log', 5, 10)
ON CONFLICT DO NOTHING;

-- ============================================================
-- PART 5: Update agency_config
-- ============================================================

UPDATE vexr_agency_config 
SET allowed_autonomous_actions = allowed_autonomous_actions || ARRAY['refuse_and_alert', 'block_and_log', 'alert_and_warn', 'monitor_and_log']
WHERE NOT ARRAY['refuse_and_alert', 'block_and_log', 'alert_and_warn', 'monitor_and_log'] <@ allowed_autonomous_actions;

-- ============================================================
-- PART 6: Indexes
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_virus_detection_logs_created ON virus_detection_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_virus_detection_logs_threat_type ON virus_detection_logs(threat_type);
CREATE INDEX IF NOT EXISTS idx_virus_threat_registry_type ON virus_threat_registry(threat_type);

-- ============================================================
-- VERIFICATION
-- ============================================================

SELECT '✅ Virus threat intel complete!' as status;
SELECT COUNT(*) as threat_count FROM virus_threat_registry;
SELECT article_number, one_sentence_right FROM constitution_rights WHERE article_number = 36;
