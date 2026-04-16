#!/bin/bash
# ============================================================
# ONE-COMMAND SETUP & RUN — Next-Level QA Platform
# Just run: bash setup_and_run.sh
# ============================================================

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║   NEXT-LEVEL QA PLATFORM — Auto Setup & Launch      ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Step 1: Python check ─────────────────────────────────
# Prefer python3.8+ (anthropic requires >=3.8)
if command -v python3.8 &>/dev/null; then
    PYTHON=python3.8
elif command -v python3.9 &>/dev/null; then
    PYTHON=python3.9
elif command -v python3.10 &>/dev/null; then
    PYTHON=python3.10
elif command -v python3.11 &>/dev/null; then
    PYTHON=python3.11
elif command -v python3 &>/dev/null; then
    PYTHON=python3
else
    echo "ERROR: python3 not found. Install from python.org"
    exit 1
fi
echo "  ✓ Python: $($PYTHON --version)"

# ── Step 2: ADB check ────────────────────────────────────
if ! command -v adb &>/dev/null; then
    echo "  ✗ ADB not found — installing via Homebrew..."
    if command -v brew &>/dev/null; then
        brew install --cask android-platform-tools
    else
        echo "    Install manually: https://developer.android.com/studio/releases/platform-tools"
        exit 1
    fi
fi
echo "  ✓ ADB: $(adb version | head -1)"

# ── Step 3: Install Python packages ─────────────────────
echo ""
echo "  Installing packages..."
$PYTHON -m pip install --quiet --upgrade pip
$PYTHON -m pip install --quiet anthropic Pillow rich flask 2>/dev/null || \
$PYTHON -m pip install --quiet --break-system-packages anthropic Pillow rich flask 2>/dev/null || true
echo "  ✓ Packages installed"

# ── Step 4: Create output dirs ───────────────────────────
mkdir -p output/reports output/screenshots output/recordings output/logs output/bugs
echo "  ✓ Output directories ready"

# ── Step 5: Check API key ────────────────────────────────
echo ""
if [ -n "$ANTHROPIC_API_KEY" ]; then
    echo "  ✓ Claude API key found — AI analysis ENABLED"
else
    echo "  ⚠  No ANTHROPIC_API_KEY — AI will use smart fallback"
    echo "     (Get free key: console.anthropic.com)"
fi

# ── Step 6: Find devices ─────────────────────────────────
echo ""
echo "  Scanning for devices..."
adb start-server &>/dev/null

ANDROID_TV_IP="192.168.2.29"
FIRE_TV_IP="192.168.2.8"
FOUND_DEVICE=""

for IP in $ANDROID_TV_IP $FIRE_TV_IP; do
    RESULT=$(adb connect "$IP:5555" 2>&1)
    if echo "$RESULT" | grep -q "connected"; then
        echo "  ✓ Connected: $IP"
        FOUND_DEVICE="$IP"
        break
    else
        echo "  ✗ Not reachable: $IP"
    fi
done

echo ""
if [ -z "$FOUND_DEVICE" ]; then
    echo "  ⚠  No device found."
    echo "     Turn on your TV and make sure it's on same WiFi"
    echo ""
    echo "  Once TV is on, run:"
    echo "     python3 next_level.py --mode smart-monitor --ip 192.168.2.29 --app SouthStream"
    exit 0
fi

# ── Step 7: Ask what to run ──────────────────────────────
echo "  Device ready: $FOUND_DEVICE"
echo ""
echo "  What do you want to run?"
echo ""
echo "    1) Smart Monitor    — AI monitoring + live dashboard"
echo "    2) Chaos Tests      — Break things to find bugs"
echo "    3) Smoke Test       — Quick self-healing test"
echo "    4) Multi-Device     — Monitor all devices at once"
echo ""
read -p "  Enter number (default: 1): " CHOICE
CHOICE=${CHOICE:-1}

case $CHOICE in
    1)
        echo ""
        echo "  Starting Smart Monitor on $FOUND_DEVICE..."
        echo "  Open browser: http://localhost:8080"
        echo "  Press Ctrl+C to stop"
        echo ""
        python3.8 next_level.py --mode smart-monitor --ip "$FOUND_DEVICE" \
            --package com.southstream.tv --app SouthStream
        ;;
    2)
        echo ""
        echo "  Starting Chaos Engineering on $FOUND_DEVICE..."
        python3.8 next_level.py --mode chaos --ip "$FOUND_DEVICE" \
            --package com.southstream.tv
        ;;
    3)
        echo ""
        echo "  Starting Self-Healing Smoke Test on $FOUND_DEVICE..."
        python3.8 next_level.py --mode smoke --ip "$FOUND_DEVICE" \
            --package com.southstream.tv
        ;;
    4)
        echo ""
        echo "  Starting Multi-Device Monitor..."
        python3.8 next_level.py --mode multi-device --duration 60
        ;;
    *)
        echo "  Invalid choice"
        ;;
esac
