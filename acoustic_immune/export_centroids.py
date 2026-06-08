#!/usr/bin/env python3
"""
Export class centroids for frontend inference using cosine similarity.
This matches the YAMNet approach but with your own collected data.
"""

import numpy as np
import json
import os

def main():
    # Load features
    data = np.load("./data/features/features.npz", allow_pickle=True)
    X = data["X"]
    y = data["y"]
    classes = data["classes"].tolist()
    
    print(f"Loaded {len(X)} samples, {X.shape[1]} features")
    print(f"Classes: {classes}")
    
    # Compute centroids
    centroids = []
    for class_name in classes:
        mask = y == class_name
        centroid = np.mean(X[mask], axis=0)
        centroids.append(centroid)
        print(f"  {class_name}: {len(X[mask])} samples → centroid shape {centroid.shape}")
    
    centroids = np.array(centroids)
    
    # Save centroids
    os.makedirs("./data/models", exist_ok=True)
    np.savez_compressed("./data/models/class_centroids.npz",
                        centroids=centroids,
                        classes=classes,
                        threshold=0.7)
    
    print("\n✅ Centroids saved to ./data/models/class_centroids.npz")
    print(f"   Shape: {centroids.shape}")
    
    # Also export as JSON for frontend
    centroids_list = [c.tolist() for c in centroids]
    with open("./data/models/class_centroids.json", "w") as f:
        json.dump({
            "centroids": centroids_list,
            "classes": classes,
            "threshold": 0.7
        }, f)
    
    print("✅ Also exported as JSON for frontend")

if __name__ == "__main__":
    main()
