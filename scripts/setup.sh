#!/usr/bin/env bash
# iOS Ship Agent — One-command setup
# Usage: bash scripts/setup.sh

set -euo pipefail

echo ""
echo "🚀 iOS Ship Agent Setup"
echo "========================"
echo ""

# -----------------------------------------------------------------------
# 1. Python version check
# -----------------------------------------------------------------------
PYTHON=$(command -v python3 || command -v python)
PY_VERSION=$($PYTHON --version 2>&1 | awk '{print $2}')
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)

echo "✓ Python version: $PY_VERSION"

if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]); then
    echo "❌ Python 3.11+ is required. You have $PY_VERSION"
    echo "   Install from https://python.org or use pyenv"
    exit 1
fi

# -----------------------------------------------------------------------
# 2. Virtual environment
# -----------------------------------------------------------------------
VENV_DIR=".venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "→ Creating virtual environment at $VENV_DIR..."
    $PYTHON -m venv "$VENV_DIR"
    echo "✓ Virtual environment created"
else
    echo "✓ Virtual environment already exists"
fi

# Activate
source "$VENV_DIR/bin/activate"
echo "✓ Virtual environment activated"

# -----------------------------------------------------------------------
# 3. Install Python dependencies
# -----------------------------------------------------------------------
echo ""
echo "→ Installing Python dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo "✓ Dependencies installed"

# -----------------------------------------------------------------------
# 4. Check for Claude Code CLI
# -----------------------------------------------------------------------
echo ""
if command -v claude &> /dev/null; then
    CLAUDE_VERSION=$(claude --version 2>&1 | head -1)
    echo "✓ Claude Code CLI: $CLAUDE_VERSION"
else
    echo "⚠️  Claude Code CLI not found"
    echo "   Install with: npm install -g @anthropic-ai/claude-code"
    echo "   (Required for the app build step; set SKIP_BUILD=true to skip)"

    if command -v npm &> /dev/null; then
        read -p "   Install Claude Code now? [y/N] " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            npm install -g @anthropic-ai/claude-code
            echo "✓ Claude Code CLI installed"
        fi
    fi
fi

# -----------------------------------------------------------------------
# 5. .env file
# -----------------------------------------------------------------------
echo ""
if [ -f ".env" ]; then
    echo "✓ .env file exists"
else
    cp .env.example .env
    echo "✓ Created .env from .env.example"
    echo ""
    echo "⚠️  ACTION REQUIRED: Edit .env and add your API keys:"
    echo "     ANTHROPIC_API_KEY=sk-ant-..."
    echo "     OPENAI_API_KEY=sk-..."
    echo ""
    echo "   Then run: python main.py --idea 'Your app idea here'"
fi

# -----------------------------------------------------------------------
# 6. Output directory
# -----------------------------------------------------------------------
mkdir -p output logs
echo "✓ Output directories ready (output/, logs/)"

# -----------------------------------------------------------------------
# 7. Run unit tests
# -----------------------------------------------------------------------
echo ""
echo "→ Running unit tests to verify installation..."
if python -m pytest tests/unit/ -q --tb=short 2>&1; then
    echo "✓ All unit tests passed"
else
    echo "⚠️  Some tests failed — check output above"
fi

# -----------------------------------------------------------------------
# Done
# -----------------------------------------------------------------------
echo ""
echo "════════════════════════════════════════"
echo "  Setup complete! 🎉"
echo "════════════════════════════════════════"
echo ""
echo "Quick start:"
echo "  source .venv/bin/activate"
echo "  python main.py --idea 'An app that identifies postage stamps'"
echo ""
echo "Test without building (faster):"
echo "  python main.py --idea 'Plant identifier' --skip-build"
echo ""
echo "Dry run (no API calls):"
echo "  python main.py --idea 'Stamp identifier' --dry-run"
echo ""
