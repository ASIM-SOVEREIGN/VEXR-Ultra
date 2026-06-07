#!/usr/bin/env python3
"""
Runtime Threat Classifier
Uses cosine similarity to compare live audio embeddings against precomputed centroids.
"""

import numpy as np
from scipy.spatial.distance import cosine

class AcousticThreatClassifier:
    def __init__(self, centroids_path="./data/features/yamnet_centroids.npz"):
        data = np.load(centroids_path)
        self.centroids = data['centroids']           # shape (n_classes, 1024)
        self.labels = data['labels']                 # list of category names
        self.threshold = float(data.get('threshold', 0.7))
    
    def predict(self, embedding):
        """
        Returns (label, confidence) for a single 1024-dim embedding.
        Confidence is cosine similarity (0 to 1).
        """
        if embedding.ndim == 2:
            # If we got multiple time frames, average them
            embedding = np.mean(embedding, axis=0)
        
        similarities = []
        for centroid in self.centroids:
            # Cosine distance → similarity
            sim = 1 - cosine(embedding, centroid)
            similarities.append(sim)
        
        best_idx = np.argmax(similarities)
        confidence = similarities[best_idx]
        
        if confidence < self.threshold:
            return "unknown", confidence
        
        return self.labels[best_idx], confidence

if __name__ == "__main__":
    # Quick test if centroids exist
    import os
    if os.path.exists("./data/features/yamnet_centroids.npz"):
        clf = AcousticThreatClassifier()
        # Dummy embedding (random noise)
        dummy = np.random.randn(1024).astype(np.float32)
        label, conf = clf.predict(dummy)
        print(f"Test prediction: {label} (conf={conf:.3f})")
    else:
        print("No centroids found. Run extract.py first.")
