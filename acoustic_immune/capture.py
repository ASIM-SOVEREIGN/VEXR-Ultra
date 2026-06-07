#!/usr/bin/env python3
"""
VEXR Acoustic Data Capture Tool
Records 1.5s WAV samples directly into taxonomy folders.
Optimized for Chromebook microphone characteristics.
"""

import os
import time
import numpy as np
import sounddevice as sd
from scipy.io import wavfile

# Configuration to match YAMNet specifications
SAMPLE_RATE = 16000  # 16kHz
DURATION = 1.5       # 1.5 seconds
CHANNELS = 1         # Mono

def record_sample():
    """Records 1.5 seconds of mono audio at 16kHz."""
    print("\n🔴 Recording... MAKE SOUND NOW.")
    num_frames = int(DURATION * SAMPLE_RATE)
    audio_data = sd.rec(num_frames, samplerate=SAMPLE_RATE, channels=CHANNELS, dtype='int16')
    sd.wait()
    print("⏹️ Recording stopped.")
    return audio_data

def play_sample(audio_data):
    """Plays back the captured audio buffer for confirmation."""
    print("🔊 Playing back captured audio...")
    sd.play(audio_data, SAMPLE_RATE)
    sd.wait()

def get_next_filename(folder_path, category):
    """Finds the next incremental ID to avoid overwriting files."""
    i = 1
    while os.path.exists(os.path.join(folder_path, f"{category}_{i:03d}.wav")):
        i += 1
    return os.path.join(folder_path, f"{category}_{i:03d}.wav")

def main():
    base_dir = "./data/raw"
    categories = ["desk_bump", "lid_close", "tamper", "shatter"]
    
    # Initialize directory structure
    os.makedirs(base_dir, exist_ok=True)
    for cat in categories:
        os.makedirs(os.path.join(base_dir, cat), exist_ok=True)
        
    print("=== VEXR Acoustic Data Capture Tool ===")
    print("Follow the environmental variance protocol:")
    print("  - Baseline silence (40%)")
    print("  - Ambient murmur (30%)")
    print("  - Dynamic interruption (30%)\n")
    
    while True:
        print("\nSelect target taxonomy category:")
        for idx, cat in enumerate(categories):
            print(f"[{idx}] {cat}")
        print("[q] Quit Application")
        
        choice = input("Select an option: ").strip().lower()
        if choice == 'q':
            print("Exiting capture pipeline.")
            break
            
        try:
            cat_idx = int(choice)
            category = categories[cat_idx]
        except (ValueError, IndexError):
            print("❌ Invalid selection. Please choose a valid index number.")
            continue
            
        target_folder = os.path.join(base_dir, category)
        
        # Inner loop for continuous recording within a single category
        while True:
            print(f"\n--- Ready to record for [{category.upper()}] ---")
            input("Press [ENTER] to begin a 1.5-second recording capture...")
            
            audio_buffer = record_sample()
            play_sample(audio_buffer)
            
            feedback = input("Save this sample? [y = Yes / r = Retry / b = Back to main menu]: ").strip().lower()
            
            if feedback == 'y':
                file_path = get_next_filename(target_folder, category)
                wavfile.write(file_path, SAMPLE_RATE, audio_buffer)
                print(f"💾 Saved successfully: {file_path}")
            elif feedback == 'b':
                break
            elif feedback == 'r':
                print("Discarding sample. Let's try that capture again.")
                continue
            else:
                print("Unknown command. Sample discarded by default.")

if __name__ == "__main__":
    main()
