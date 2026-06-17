#!/bin/bash

# ─────────────────────────────────────────────
# ScamShield Launcher — Graphura India / Team-J
# Double-click this file to start the project
# ─────────────────────────────────────────────

PROJECT_DIR="/Users/sakshamchauhan/Desktop/Team-j_Fake-Internship-Job-Scam-Detection-System"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
APP_PATH="$PROJECT_DIR/scam_detector/app.py"

echo ""
echo "=================================================="
echo "   🛡️  ScamShield — Starting Up"
echo "   Graphura India Private Limited · Team-J"
echo "=================================================="
echo ""

# Check project folder exists
if [ ! -d "$PROJECT_DIR" ]; then
    echo "❌ Project folder not found at:"
    echo "   $PROJECT_DIR"
    echo "   Update PROJECT_DIR in this script."
    read -p "Press Enter to exit..."
    exit 1
fi

# Check venv exists
if [ ! -f "$VENV_PYTHON" ]; then
    echo "❌ Virtual environment not found at:"
    echo "   $PROJECT_DIR/.venv"
    echo "   Run: python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    read -p "Press Enter to exit..."
    exit 1
fi

# Check app.py exists
if [ ! -f "$APP_PATH" ]; then
    echo "❌ app.py not found at: $APP_PATH"
    read -p "Press Enter to exit..."
    exit 1
fi

cd "$PROJECT_DIR"

# Activate venv
source "$PROJECT_DIR/.venv/bin/activate"

echo "✅ Virtual environment activated"
echo "✅ Project directory: $PROJECT_DIR"
echo ""

# Open VS Code (optional — comment out if not needed)
if command -v code &> /dev/null; then
    echo "📂 Opening VS Code..."
    code "$PROJECT_DIR" &
fi

# Wait a moment then open browser
(sleep 3 && open "http://127.0.0.1:5001") &

echo "🚀 Starting Flask server on http://127.0.0.1:5001"
echo "   Press Ctrl+C to stop the server"
echo ""
echo "=================================================="
echo ""

# Run the Flask app
"$VENV_PYTHON" "$APP_PATH"

# If Flask exits
echo ""
echo "⚠️  Server stopped."
read -p "Press Enter to close..."
