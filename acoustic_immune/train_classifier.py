#!/usr/bin/env python3
"""
Train Random Forest classifier on extracted features.
"""

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import classification_report, confusion_matrix
import joblib
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
    
    # Convert labels to indices
    label_map = {name: i for i, name in enumerate(classes)}
    y_idx = np.array([label_map[name] for name in y])
    
    # Split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y_idx, test_size=0.2, random_state=42, stratify=y_idx
    )
    
    print(f"Training: {len(X_train)} samples")
    print(f"Test: {len(X_test)} samples")
    
    # Train with cross-validation
    clf = RandomForestClassifier(
        n_estimators=100,
        max_depth=10,
        min_samples_split=5,
        random_state=42,
        n_jobs=-1
    )
    
    # Cross-validation
    cv_scores = cross_val_score(clf, X_train, y_train, cv=5)
    print(f"\n📊 Cross-validation scores: {cv_scores}")
    print(f"   Mean CV accuracy: {cv_scores.mean():.3f} ± {cv_scores.std():.3f}")
    
    # Train final model
    clf.fit(X_train, y_train)
    
    # Evaluate
    y_pred = clf.predict(X_test)
    print("\n" + "="*50)
    print("CLASSIFICATION REPORT")
    print("="*50)
    print(classification_report(y_test, y_pred, target_names=classes))
    
    print("\n" + "="*50)
    print("CONFUSION MATRIX")
    print("="*50)
    cm = confusion_matrix(y_test, y_pred)
    print(cm)
    
    # Feature importance
    feature_names = ["rms", "centroid", "zcr"] + [f"mfcc_{i}" for i in range(13)]
    importance = clf.feature_importances_
    top_idx = np.argsort(importance)[-5:][::-1]
    print("\n📊 Top 5 most important features:")
    for i in top_idx:
        print(f"   {feature_names[i]}: {importance[i]:.3f}")
    
    # Save model
    os.makedirs("./data/models", exist_ok=True)
    joblib.dump(clf, "./data/models/acoustic_classifier.pkl")
    print("\n✅ Model saved to ./data/models/acoustic_classifier.pkl")
    
    # Save feature names
    with open("./data/models/feature_names.json", "w") as f:
        json.dump(feature_names, f)
    
    # Save class map
    with open("./data/models/class_map.json", "w") as f:
        json.dump(label_map, f)
    
    # Save class names
    with open("./data/models/class_names.json", "w") as f:
        json.dump(classes, f)

if __name__ == "__main__":
    main()
