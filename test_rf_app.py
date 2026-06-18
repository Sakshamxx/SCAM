#!/usr/bin/env python3
"""Comprehensive test of Random Forest model loading in Flask app"""

import sys
import os
from pathlib import Path

# Setup path
sys.path.insert(0, '/Users/sakshamchauhan/SCAM')
os.chdir('/Users/sakshamchauhan/SCAM')

# Set Flask to test mode
os.environ['FLASK_ENV'] = 'testing'
os.environ['PYTHONUNBUFFERED'] = '1'

print("\n" + "=" * 70)
print("RANDOM FOREST MODEL LOADING TEST")
print("=" * 70 + "\n")

# Import the app (this will trigger model loading)
try:
    from scam_detector.app import (
        nlp_pipeline,
        logistic_model,
        random_forest_model,
        scaler,
        le_location,
        le_title,
    )
    
    print("\n✅ Models imported successfully from app.py\n")
    
    # Check status
    print("Model Loading Status:")
    print("-" * 70)
    print(f"NLP Pipeline:           {'✅ Loaded' if nlp_pipeline else '❌ Missing'}")
    print(f"Logistic Model:         {'✅ Loaded' if logistic_model else '❌ Missing'}")
    print(f"Random Forest:          {'✅ Loaded' if random_forest_model else '❌ Missing'}")
    print(f"Scaler:                 {'✅ Loaded' if scaler else '❌ Missing'}")
    print(f"LE Location:            {'✅ Loaded' if le_location else '❌ Missing'}")
    print(f"LE Title:               {'✅ Loaded' if le_title else '❌ Missing'}")
    print("-" * 70)
    
    if random_forest_model:
        print(f"\n✅ SUCCESS: Random Forest model type: {type(random_forest_model).__name__}")
        print(f"✅ Model has predict method: {hasattr(random_forest_model, 'predict')}")
    else:
        print("\n❌ FAILED: Random Forest model is None")
    
except ImportError as e:
    print(f"\n❌ Import Error: {e}")
    import traceback
    traceback.print_exc()
except Exception as e:
    print(f"\n❌ Unexpected Error: {repr(e)}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 70 + "\n")
