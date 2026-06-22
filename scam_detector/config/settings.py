import os
from pathlib import Path
from dotenv import load_dotenv
from datetime import timedelta

# Load environment variables
load_dotenv()

# Base paths
BASE_DIR = Path(__file__).parent.parent
MODEL_DIR = BASE_DIR / 'models'
UPLOADS_DIR = BASE_DIR / 'uploads'

# Secret keys & configs
SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SECRET_KEY", "default-scamshield-secret-key-12345")
PERMANENT_SESSION_LIFETIME = timedelta(days=30)

# Supabase Credentials
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_ANON_KEY")
