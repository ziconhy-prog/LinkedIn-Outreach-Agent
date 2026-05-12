#!/bin/bash
# LinkedIn Outreach Agent — one-time setup
# Double-click this file from Finder. It installs Python dependencies,
# creates the local database, and gets you ready for daily use.

set -e
cd "$(dirname "$0")"

echo "================================================="
echo "  LinkedIn Outreach Agent — Setup"
echo "================================================="
echo ""

# 1. Check Python is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed on this Mac."
    echo "   Download it from https://www.python.org/downloads/"
    echo "   Then double-click this file again."
    echo ""
    read -n 1 -s -r -p "Press any key to close..."
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "✅ Python ${PYTHON_VERSION} detected"

# 2. Verify Python 3.11 or newer
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    echo "❌ Python 3.11 or newer is required (you have ${PYTHON_VERSION})."
    echo "   Install a newer version from https://www.python.org/downloads/"
    echo ""
    read -n 1 -s -r -p "Press any key to close..."
    exit 1
fi

# 3. Create virtualenv if absent
if [ ! -d ".venv" ]; then
    echo "📦 Creating Python virtual environment..."
    python3 -m venv .venv
else
    echo "✅ Virtual environment already exists"
fi

# 4. Activate venv and install dependencies
echo "📦 Installing dependencies..."
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
echo "✅ Dependencies installed"

# 4b. Install the Chromium browser Playwright drives (≈170 MB, one time)
if [ ! -d "$HOME/Library/Caches/ms-playwright" ] || \
   [ -z "$(ls -A "$HOME/Library/Caches/ms-playwright" 2>/dev/null)" ]; then
    echo "🌐 Installing Chromium for Playwright (one-time, ~170 MB)..."
    python -m playwright install chromium
else
    echo "✅ Chromium for Playwright already installed"
fi

# 5. Copy .env.example -> .env if .env doesn't exist
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "✅ Created .env (you'll fill it in as later phases activate)"
else
    echo "✅ .env already exists"
fi

# 6. Make sure data/ and logs/ directories exist
mkdir -p data logs
echo "✅ data/ and logs/ directories ready"

# 7. Initialize the database (idempotent — safe to re-run)
echo "💾 Initializing database..."
python -m outreach init-db

echo ""
echo "================================================="
echo "  Setup complete!"
echo "================================================="
echo ""
echo "What's working now:"
echo "  • Database is initialized"
echo "  • Voice samples can be loaded"
echo "  • BNI PDF can be parsed (place it at data/bni_members.pdf)"
echo ""
echo "Coming in later phases:"
echo "  • Telegram bot, LinkedIn integration, Calendar booking"
echo ""
read -n 1 -s -r -p "Press any key to close..."
echo ""
