#!/usr/bin/env bash
# Android TV Automation — one-shot setup script
# Run once before first use: bash setup.sh

set -e

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  Android TV Automation — Setup               ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ── Python check ─────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
  echo "ERROR: python3 not found. Install Python 3.9+ first."
  exit 1
fi
PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "✓ Python $PY_VERSION found"

# ── ADB check ────────────────────────────────────────────────────────────────
if ! command -v adb &>/dev/null; then
  echo ""
  echo "WARNING: adb not found on PATH."
  echo "Install Android SDK Platform Tools:"
  echo "  macOS  : brew install android-platform-tools"
  echo "  Linux  : sudo apt install adb"
  echo "  Manual : https://developer.android.com/studio/releases/platform-tools"
  echo ""
else
  ADB_VER=$(adb version | head -1)
  echo "✓ $ADB_VER"
fi

# ── Virtual environment ───────────────────────────────────────────────────────
VENV_DIR="$(pwd)/venv"
if [ ! -d "$VENV_DIR" ]; then
  echo "→ Creating virtual environment at $VENV_DIR ..."
  python3 -m venv "$VENV_DIR"
fi
echo "✓ Virtual environment ready"

# ── Activate & install ────────────────────────────────────────────────────────
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"
echo "→ Installing Python dependencies ..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "✓ Dependencies installed"

# ── Output directories ───────────────────────────────────────────────────────
mkdir -p output/screenshots output/logs output/reports
echo "✓ Output directories created"

echo ""
echo "══════════════════════════════════════════════"
echo "  Setup complete!"
echo ""
echo "  Next steps:"
echo "  1. Enable ADB over WiFi on your Android TV:"
echo "     Settings → Device Preferences → About → Build (click 7×)"
echo "     Then: Settings → Device Preferences → Developer Options → ADB Debugging ON"
echo ""
echo "  2. Find your device IP:"
echo "     Settings → Network & Internet → (your WiFi) → IP address"
echo ""
echo "  3. Edit config.py:"
echo "     device_ip   = 'YOUR_TV_IP'"
echo "     package_name = 'YOUR_APP_PACKAGE'"
echo ""
echo "  4. Run the monitor:"
echo "     source venv/bin/activate"
echo "     python main.py --ip 192.168.1.100 --package com.example.ottapp"
echo ""
echo "  Optional flags:"
echo "     --duration 2.5      (hours, 0=infinite)"
echo "     --web               (enable web dashboard on :8080)"
echo "     --no-dashboard      (disable rich terminal UI)"
echo "     --no-screenshots    (skip screenshot capture)"
echo "     --debug             (verbose logging)"
echo "══════════════════════════════════════════════"
echo ""
