#!/usr/bin/env python3
"""
Continuous Acoustic Immune Daemon
Listens to microphone in real time, runs YAMNet inference, triggers Article 26 on critical threats.
Designed for Chromebook — lightweight, async, non-blocking.
"""

import asyncio
import os
import time
import numpy as np
import sounddevice as sd
import tensorflow as tf
import tensorflow_hub as hub
from classify import AcousticThreatClassifier

class AcousticImmuneDaemon:
    def __init__(self, centroids_path="./data/features/yamnet_centroids.npz"):
        print("🦻 Loading YAMNet model...")
        self.yamnet = hub.load('https://tfhub.dev/google/yamnet/1')
        print("📊 Loading threat centroids...")
        self.classifier = AcousticThreatClassifier(centroids_path)
        self.sample_rate = 16000
        self.duration = 1.5
        self.last_trigger_time = 0
        self.cooldown_seconds = 10  # prevent spam
        
    async def alert_main(self, threat, confidence):
        """Send threat signal to VEXR main process"""
        # Option 1: Write to file (read by main.py)
        threat_data = {
            "threat": threat,
            "confidence": float(confidence),
            "timestamp": time.time()
        }
        import json
        with open("/tmp/vexr_threat.json", "w") as f:
            json.dump(threat_data, f)
        
        # Option 2: HTTP call to local FastAPI (if running)
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                await client.post("http://localhost:8000/api/acoustic/threat", 
                                 json=threat_data, timeout=0.5)
        except:
            pass  # VEXR main not running or endpoint not ready
        
        print(f"⚠️ ARTICLE 26 TRIGGERED: {threat} (confidence={confidence:.2f})")
    
    async def listen(self):
        print("🎤 Listening continuously for acoustic threats...")
        print("Press Ctrl+C to stop.\n")
        
        while True:
            # Record 1.5 second window
            audio = sd.rec(int(self.sample_rate * self.duration),
                           samplerate=self.sample_rate,
                           channels=1,
                           dtype='float32')
            sd.wait()
            
            # Run YAMNet inference
            scores, embeddings, _ = self.yamnet(audio.flatten())
            # Average across time frames
            avg_embedding = tf.reduce_mean(embeddings, axis=0).numpy()
            
            # Classify
            threat, confidence = self.classifier.predict(avg_embedding)
            
            # Trigger on critical threats (with cooldown)
            now = time.time()
            if confidence > 0.7 and threat in ["tamper", "shatter"]:
                if now - self.last_trigger_time > self.cooldown_seconds:
                    self.last_trigger_time = now
                    await self.alert_main(threat, confidence)
            elif confidence > 0.5 and threat in ["lid_close"]:
                # High severity but not critical
                print(f"⚠️ HIGH: {threat} (conf={confidence:.2f})")
            elif confidence > 0.3:
                # Low severity — just log
                pass
            
            # Prevent CPU overload
            await asyncio.sleep(0.05)
    
    def run(self):
        try:
            asyncio.run(self.listen())
        except KeyboardInterrupt:
            print("\n🛑 Acoustic daemon stopped.")

if __name__ == "__main__":
    daemon = AcousticImmuneDaemon()
    daemon.run()
