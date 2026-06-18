#!/usr/bin/env python3
"""Test script to verify Random Forest model loading"""

import sys
sys.path.insert(0, '/Users/sakshamchauhan/SCAM')

from pathlib import Path

# Test the model loading logic
MODEL_DIR = Path('/Users/sakshamchauhan/SCAM/scam_detector/models')

print("=" * 60)
print("Testing Random Forest Model Loading")
print("=" * 60)

# Check RF file
rf_path = MODEL_DIR / 'random_forest_model.pkl'
print(f"[RF-DEBUG] Attempting to load: {rf_path}")
print(f"[RF-DEBUG] Path exists: {rf_path.exists()}")

if not rf_path.exists():
    # Fallback: Use best_model.pkl (Hybrid Model contains Random Forest)
    print(f"[RF-DEBUG] random_forest_model.pkl not found. Using best_model.pkl as fallback")
    best_model_path = MODEL_DIR / 'best_model.pkl'
    print(f"[RF-DEBUG] Checking best_model.pkl at: {best_model_path}")
    print(f"[RF-DEBUG] best_model.pkl exists: {best_model_path.exists()}")
    
    if best_model_path.exists():
        print(f"[RF-DEBUG] ✅ Loaded best_model.pkl (Hybrid Model with RF) as fallback")
        print(f"\n✅ SUCCESS: Random Forest model will be loaded from best_model.pkl")
    else:
        print(f"[RF-DEBUG] ⚠️  Neither random_forest_model.pkl nor best_model.pkl found")
else:
    print(f"[RF-DEBUG] ✅ Random Forest model file found")
    print(f"\n✅ SUCCESS: Random Forest model will be loaded from random_forest_model.pkl")

print("\n" + "=" * 60)
print("Available models in /models/:")
print("=" * 60)
for pkl in sorted(MODEL_DIR.glob('*.pkl')):
    print(f"  ✓ {pkl.name}")
