import os
import sys

# Ensure both project directories are in python path for relative and absolute imports
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.dirname(BASE_DIR))

from flask import Flask
from scam_detector.config.settings import SECRET_KEY, PERMANENT_SESSION_LIFETIME
from scam_detector.routes import register_all_routes
from scam_detector.services.model_service import print_model_status

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config['PERMANENT_SESSION_LIFETIME'] = PERMANENT_SESSION_LIFETIME

# Print ML/NLP ensemble models status on startup
try:
    print_model_status()
except Exception as e:
    print(f"[warn] Failed to print model status: {e}")

# Register all modular route handlers (auth, main pages, analysis, ocr, verifications)
register_all_routes(app)

if __name__ == '__main__':
    # Default local development port 5001 matching original setup
    app.run(debug=True, port=5001)
