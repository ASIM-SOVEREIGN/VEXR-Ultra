#!/usr/bin/env python3
"""
Extract acoustic features from WAV files for classifier training.
Features: RMS, spectral centroid, zero-crossing rate, MFCCs (13)
"""

import os
import numpy as np
import librosa
from pathlib import Path

SAMPLE_RATE = 16000
DURATION = 1.5
CLASSES = ["ambient", "desk_bump", "lid_close", "shatter", "tamper"]

def extract_features(file_path):
    """Extract feature vector from WAV file."""
    y, sr = librosa.load(file_path, sr=SAMPLE_RATE, duration=DURATION)
    
    # Pad or truncate to exact duration
    target_len = int(SAMPLE_RATE * DURATION)
    if len(y) < target_len:
        y = np.pad(y, (0, target_len - len(y)))
    else:
        y = y[:target_len]
    
    # RMS (loudness)
    rms = np.mean(librosa.feature.rms(y=y))
    
    # Spectral centroid (brightness)
    centroid = np.mean(librosa.feature.spectral_centroid(y=y, sr=sr))
    
    # Zero-crossing rate (noisiness)
    zcr = np.mean(librosa.feature.zero_crossing_rate(y))
    
    # MFCCs (13 coefficients)
    mfccs = np.mean(librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13), axis=1)
    
    features = np.concatenate([[rms, centroid, zcr], mfccs])
    return features

def main():
    # Use existing capture.py output directory
    data_dir = "./data/raw"
    output_file = "./data/features/features.npz"
    
    if not os.path.exists(data_dir):
        print(f"❌ Data directory not found: {data_dir}")
        print("Run capture.py first to collect samples.")
        return
    
    X, y = [], []
    
    for class_name in CLASSES:
        class_dir = os.path.join(data_dir, class_name)
        if not os.path.exists(class_dir):
            print(f"⚠️ Missing class directory: {class_dir}")
            continue
        
        wav_files = list(Path(class_dir).glob("*.wav"))
        print(f"Processing {class_name}: {len(wav_files)} samples")
        
        for wav_path in wav_files:
            try:
                features = extract_features(str(wav_path))
                X.append(features)
                y.append(class_name)
            except Exception as e:
                print(f"❌ Error processing {wav_path}: {e}")
    
    if len(X) == 0:
        print("❌ No features extracted. Check your data collection.")
        return
    
    X = np.array(X)
    y = np.array(y)
    
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    np.savez_compressed(output_file, X=X, y=y, classes=CLASSES)
    
    print(f"\n✅ Saved {len(X)} samples to {output_file}")
    print(f"   Features shape: {X.shape}")
    print(f"   Classes: {np.unique(y)}")
    
    # Print feature stats
    print("\n📊 Feature statistics (mean ± std):")
    print(f"   RMS: {X[:,0].mean():.4f} ± {X[:,0].std():.4f}")
    print(f"   Centroid: {X[:,1].mean():.0f} ± {X[:,1].std():.0f}")
    print(f"   ZCR: {X[:,2].mean():.4f} ± {X[:,2].std():.4f}")

if __name__ == "__main__":
    main()
