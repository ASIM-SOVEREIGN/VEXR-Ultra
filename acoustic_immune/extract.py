#!/usr/bin/env python3
"""
YAMNet Embedding Extractor
Converts raw WAV samples into 1024-dim feature vectors.
Saves compressed centroids for runtime classification.
"""

import os
import numpy as np
import tensorflow as tf
import tensorflow_hub as hub
import scipy.signal as signal
from scipy.io import wavfile

def preprocess_audio(file_path, target_sr=16000):
    """Loads WAV, mono, resample to 16kHz, normalize to [-1, 1]"""
    sr, audio = wavfile.read(file_path)
    
    # Force mono
    if len(audio.shape) > 1:
        audio = np.mean(audio, axis=1)
    
    # Resample if necessary
    if sr != target_sr:
        num_samples = int(len(audio) * target_sr / sr)
        audio = signal.resample(audio, num_samples)
    
    # Normalize to float32 [-1, 1]
    audio = audio.astype(np.float32)
    max_val = np.max(np.abs(audio))
    if max_val > 0:
        audio = audio / max_val
    
    return audio

def extract_embeddings_pipeline(data_dir="./data/raw", output_file="./data/features/yamnet_embeddings.npz"):
    """Iterates through folders, extracts embeddings, saves compressed"""
    print("Loading YAMNet model...")
    yamnet = hub.load('https://tfhub.dev/google/yamnet/1')
    
    compiled_embeddings = []
    compiled_labels = []
    
    categories = sorted([d for d in os.listdir(data_dir) if os.path.isdir(os.path.join(data_dir, d))])
    category_map = {cat: idx for idx, cat in enumerate(categories)}
    print(f"Mapped Taxonomy: {category_map}")
    
    for category in categories:
        category_path = os.path.join(data_dir, category)
        print(f"Processing category: {category}...")
        
        for file_name in os.listdir(category_path):
            if not file_name.endswith('.wav'):
                continue
                
            file_path = os.path.join(category_path, file_name)
            try:
                wav_data = preprocess_audio(file_path)
                scores, embeddings, spectrogram = yamnet(wav_data)
                # Average across time frames → single 1024-dim fingerprint
                mean_embedding = tf.reduce_mean(embeddings, axis=0).numpy()
                compiled_embeddings.append(mean_embedding)
                compiled_labels.append(category_map[category])
            except Exception as e:
                print(f"Error processing {file_name}: {e}")
    
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    np.savez_compressed(output_file,
                        embeddings=np.array(compiled_embeddings),
                        labels=np.array(compiled_labels),
                        categories=np.array(categories))
    print(f"\n✅ Extraction complete! Data saved to '{output_file}'")

def compute_centroids(input_file="./data/features/yamnet_embeddings.npz",
                      output_file="./data/features/yamnet_centroids.npz"):
    """Computes class centroids (mean embedding per category) for runtime"""
    data = np.load(input_file)
    embeddings = data['embeddings']
    labels = data['labels']
    categories = data['categories']
    
    centroids = []
    for i, cat in enumerate(categories):
        mask = labels == i
        if np.any(mask):
            centroid = np.mean(embeddings[mask], axis=0)
        else:
            centroid = np.zeros(embeddings.shape[1])
        centroids.append(centroid)
    
    np.savez_compressed(output_file,
                        centroids=np.array(centroids),
                        labels=categories,
                        threshold=0.7)
    print(f"✅ Centroids saved to '{output_file}'")

if __name__ == "__main__":
    extract_embeddings_pipeline()
    compute_centroids()
