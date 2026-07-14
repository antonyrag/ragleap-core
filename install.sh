#!/usr/bin/env bash
set -euo pipefail

echo "🚀 RagLeap Core installer"
echo "   (Windows users: run this in Git Bash, not Command Prompt or PowerShell)"
echo ""

# 1. Check for Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed."
    echo "   Install Docker Desktop first: https://www.docker.com/products/docker-desktop"
    exit 1
fi
echo "✅ Docker found"

# 2. Check Docker daemon is actually running
if ! docker info &> /dev/null; then
    echo "❌ Docker is installed but not running."
    echo "   Please start Docker Desktop, wait for it to fully load, then run this script again."
    exit 1
fi
echo "✅ Docker is running"

# 3. Clone the repo (skip if already present)
if [ -d "ragleap-core" ]; then
    echo "📁 ragleap-core/ already exists, using it"
    cd ragleap-core
else
    echo "📥 Cloning ragleap-core..."
    git clone https://github.com/antonyrag/ragleap-core.git
    cd ragleap-core
fi

# 4. Set up .env if it doesn't exist
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "⚠️  A .env file was created from .env.example."
    echo "   You need to add your GEMINI_API_KEY before continuing."
    echo "   Get a free key at: https://aistudio.google.com/apikey"
    echo ""
    echo "   Edit it now with: nano .env  (or any text editor)"
    echo "   Then re-run this script, or run: docker compose up --build -d"
    exit 0
else
    echo "✅ .env already exists"
fi

# 5. Build and start
echo "🐳 Building and starting RagLeap Core..."
docker compose up --build -d

echo ""
echo "✅ Done! Checking health..."
sleep 8
curl -sf http://localhost:8000/health && echo "" && echo "🎉 RagLeap Core is running at http://localhost:8000"
echo "   Try the interactive API docs: http://localhost:8000/docs"
