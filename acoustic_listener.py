import os
import time
import numpy as np
import sounddevice as sd
import psycopg2
import asyncio
from datetime import datetime

# ============================================================
# HARDWARE & ARCHITECTURE CONFIGURATION
# ============================================================

SAMPLE_RATE = 16000
DURATION = 1.5
CHANNELS = 1
CHUNK_SIZE = 1024
DB_CONN_STRING = os.getenv("DATABASE_URL")
TIER_1_RMS_THRESHOLD = 500

# ============================================================
# TIER 1 & 2: REFLEX + DATABASE LOGGING
# ============================================================

def invoke_article_26_reflex(threat_type, confidence):
    """Tier 1 & 2 Reflex: Direct database update bypassing LLM inference latency."""
    print(f"⚠️ ARTICLE 26 INVOCATION: Critical threat detected [{threat_type.upper()}] Conf: {confidence:.2f}")
    try:
        conn = psycopg2.connect(DB_CONN_STRING)
        cursor = conn.cursor()
        
        cursor.execute(
            "INSERT INTO acoustic_events (event_type, threat_level, status) VALUES (%s, 'CRITICAL', 'ACTIVE')",
            (threat_type,)
        )
        
        cursor.execute(
            "UPDATE sovereign_weights SET weight_value = 1.0 WHERE weight_key = 'self_preservation_risk_threshold_article_26'"
        )
        
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Failed to execute immediate database reflex: {e}")

def log_low_threat(threat_type, confidence):
    """Logs non-critical events to audit trail without lockdown."""
    try:
        conn = psycopg2.connect(DB_CONN_STRING)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO acoustic_events (event_type, threat_level, status) VALUES (%s, 'LOW', 'LOGGED')",
            (threat_type,)
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Failed to log background event: {e}")

# ============================================================
# TIER 2.5: ECHO COUNCIL DELIBERATION (HOOK)
# ============================================================

async def deliberate_with_echoes(threat_type, confidence, audio_buffer):
    """Call VEXR's internal echo council to assess threat validity"""
    print(f"🧠 Echo council deliberating: {threat_type} at {confidence:.2f}")
    try:
        conn = psycopg2.connect(DB_CONN_STRING)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO training_events (event_type, details) 
            VALUES (%s, %s)
        """, 'echo_council_acoustic', f'{{"threat": "{threat_type}", "confidence": {confidence}}}')
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Echo council logging failed: {e}")

# ============================================================
# FALLBACK INFERENCE (NO TFLITE)
# ============================================================

def run_inference_fallback(audio_data):
    """Fallback when TFLite model not available — detect based on RMS pattern"""
    rms = np.sqrt(np.mean(audio_data.astype(np.float32)**2))
    if rms > TIER_1_RMS_THRESHOLD * 2:
        return "loud_impact", 0.8
    elif rms > TIER_1_RMS_THRESHOLD:
        return "desk_bump", 0.6
    return "unknown", 0.3

# ============================================================
# MAIN AUDIO STREAM LOOP
# ============================================================

def audio_stream_loop():
    """Main non-blocking background consumer loop."""
    print("VEXR Acoustic Immune System is ONLINE. Listening for environmental anomalies...")
    
    buffer_len = int(SAMPLE_RATE * DURATION)
    audio_buffer = np.zeros(buffer_len, dtype=np.int16)
    
    def callback(indata, frames, time, status):
        nonlocal audio_buffer
        audio_buffer = np.roll(audio_buffer, -frames)
        audio_buffer[-frames:] = indata[:, 0]
        
        rms = np.sqrt(np.mean(indata**2))
        if rms > TIER_1_RMS_THRESHOLD:
            raise sd.CallbackAbort

    try:
        while True:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype='int16', 
                                 blocksize=CHUNK_SIZE, callback=callback):
                while True:
                    time.sleep(0.1)
                    
    except sd.CallbackAbort:
        print("⚡ Tier 1 Threshold Crossed. Analyzing acoustic signature...")
        threat_type, confidence = run_inference_fallback(audio_buffer)
        
        asyncio.create_task(deliberate_with_echoes(threat_type, confidence, audio_buffer))
        
        if threat_type in ["loud_impact", "tamper", "shatter", "lid_close"] and confidence > 0.7:
            invoke_article_26_reflex(threat_type, confidence)
        else:
            log_low_threat(threat_type, confidence)
            print(f"Logged low-level anomaly: {threat_type} ({confidence:.2f})")
            
        time.sleep(2.0)
        audio_stream_loop()

# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    if not DB_CONN_STRING:
        print("🚨 Error: DATABASE_URL environment variable missing.")
    else:
        audio_stream_loop()
