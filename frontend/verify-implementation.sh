#!/bin/bash

# Verification Script for Framer Motion Cyber Background Implementation
# Run this script to verify all files are in place

echo "🔍 Verifying Framer Motion Cyber Background Implementation..."
echo ""

FRONTEND_DIR="/Users/sakshamchauhan/SCAM/frontend"

# Check main component files
echo "✓ Checking component files..."
files=(
  "src/components/effects/CyberBackground.jsx"
  "src/components/effects/CyberBackground.css"
  "src/components/auth/Login.jsx"
  "src/components/auth/Signup.jsx"
  "src/components/auth/AuthPages.css"
  "src/lib/api.js"
)

missing=0
for file in "${files[@]}"; do
  if [ -f "$FRONTEND_DIR/$file" ]; then
    echo "  ✅ $file"
  else
    echo "  ❌ $file (MISSING)"
    ((missing++))
  fi
done

echo ""
echo "✓ Checking documentation files..."
docs=(
  "CYBER_BACKGROUND_GUIDE.md"
  "FRONTEND_SETUP.md"
  "FRAMER_MOTION_REPORT.md"
  "QUICK_REFERENCE.md"
)

for doc in "${docs[@]}"; do
  if [ -f "$FRONTEND_DIR/$doc" ]; then
    echo "  ✅ $doc"
  else
    echo "  ⚠️  $doc (optional)"
  fi
done

echo ""
echo "✓ Checking App.jsx has routing..."
if grep -q "react-router-dom" "$FRONTEND_DIR/src/App.jsx"; then
  echo "  ✅ Router imports found"
else
  echo "  ❌ Router imports missing"
  ((missing++))
fi

if grep -q "/login" "$FRONTEND_DIR/src/App.jsx"; then
  echo "  ✅ Login route configured"
else
  echo "  ❌ Login route missing"
  ((missing++))
fi

if grep -q "/signup" "$FRONTEND_DIR/src/App.jsx"; then
  echo "  ✅ Signup route configured"
else
  echo "  ❌ Signup route missing"
  ((missing++))
fi

echo ""
echo "✓ Checking dependencies..."
if grep -q "framer-motion" "$FRONTEND_DIR/package.json"; then
  echo "  ✅ framer-motion installed"
else
  echo "  ⚠️  framer-motion not in package.json"
fi

if grep -q "react-router-dom" "$FRONTEND_DIR/package.json"; then
  echo "  ✅ react-router-dom installed"
else
  echo "  ⚠️  react-router-dom not in package.json"
fi

echo ""
if [ $missing -eq 0 ]; then
  echo "✨ All files verified! Implementation is complete."
  echo ""
  echo "Next steps:"
  echo "  1. cd frontend"
  echo "  2. npm run dev"
  echo "  3. Open http://localhost:5173"
  exit 0
else
  echo "❌ Found $missing missing file(s). Please check installation."
  exit 1
fi
