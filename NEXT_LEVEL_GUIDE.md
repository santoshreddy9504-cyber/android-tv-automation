# Next-Level QA Intelligence Platform — Quick Start Guide

## Install

```bash
cd "android tv automation"
pip install -r requirements_next_level.txt
```

Set your API key for AI features (optional but powerful):
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

---

## Mode 1 — AI Smart Monitor (Most Powerful)

Monitors silently in background. Every crash is analyzed by AI — explains cause, suggests exact fix, predicts next crash before it happens.

```bash
# Monitor SouthStream on Android TV
python next_level.py --mode smart-monitor --ip 192.168.2.29 --package com.southstream.tv --app SouthStream

# Monitor ROD TV
python next_level.py --mode smart-monitor --ip 192.168.2.29 --package com.webnexs.rod_tv --app "ROD TV"

# With email alerts
python next_level.py --mode smart-monitor --ip 192.168.2.29 --email-to santosh@revidd.com

# Run forever (no duration limit)
python next_level.py --mode smart-monitor --ip 192.168.2.29 --duration 0
```

**Open live dashboard in any browser:** `http://<your-mac-ip>:8080`

---

## Mode 2 — Multi-Device Parallel

Monitor Android TV + Fire TV simultaneously. One unified report.

```bash
python next_level.py --mode multi-device --duration 60
```

Edit `next_level.py` lines ~280-285 to add your device IPs.

---

## Mode 3 — Chaos Engineering

Deliberately breaks things to find hidden bugs:

```bash
# Run all chaos tests
python next_level.py --mode chaos --ip 192.168.2.29 --package com.southstream.tv

# Run specific tests only
python next_level.py --mode chaos --ip 192.168.2.29 --chaos-tests network_cut rapid_navigation kill_restart
```

Chaos tests available:
- `network_cut` — cuts WiFi for 10 seconds
- `rapid_navigation` — 50 rapid button presses
- `background_foreground` — backgrounds/foregrounds app 5 times
- `kill_restart` — force kills and measures restart time
- `low_memory` — simulates low RAM pressure
- `network_throttle` — 2G speed simulation

---

## Mode 4 — Self-Healing Smoke Test

Runs basic tests that automatically adapt if UI changes:

```bash
python next_level.py --mode smoke --ip 192.168.2.29 --package com.southstream.tv
```

---

## Mode 5 — Release Gate

Decides GO or NO-GO for a release:

```bash
# Save baseline from current build (run on a known-good build)
python next_level.py --mode release-gate --save-baseline

# Evaluate next build
python next_level.py --mode release-gate
```

---

## Environment Variables

```bash
export ANTHROPIC_API_KEY="sk-ant-..."          # AI analysis
export SLACK_WEBHOOK_URL="https://hooks.slack.com/..."  # Slack alerts
export SMTP_USER="your@gmail.com"              # Email alerts
export SMTP_PASSWORD="your-app-password"       # Gmail app password
export EMAIL_TO="santosh@revidd.com"           # Alert recipient
```

---

## What Each Module Does

| Module | File | Purpose |
|--------|------|---------|
| AI Engine | `ai_engine/crash_analyzer.py` | Claude API crash analysis |
| UX Scorer | `ai_engine/ux_scorer.py` | 0-100 UX health score |
| Crash Predictor | `prediction/crash_predictor.py` | Predict crash before it happens |
| Screen Analyzer | `vision/screen_analyzer.py` | Detect black screen, frozen frame |
| Device Fleet | `multi_device/device_fleet.py` | Multi-device parallel monitoring |
| Chaos Engineer | `chaos/chaos_engineer.py` | Chaos tests |
| Notifications | `notifications/notifier.py` | Slack + Email alerts |
| Bug Reporter | `auto_bug/bug_reporter.py` | Auto bug report generator |
| Release Gate | `release_gate/release_gate.py` | GO/NO-GO release decision |
| Self-Healing | `automation/self_healing_runner.py` | Adaptive test runner |
| Live Dashboard | `dashboard/live_dashboard.py` | Real-time web dashboard |

---

## Output Files

All output goes to `output/`:
- `output/reports/` — HTML reports
- `output/bugs/` — Auto-generated bug reports (one per crash)
- `output/screenshots/` — Screenshots
- `output/recordings/` — Screen recordings
- `output/release_baseline.json` — Release gate baseline
- `output/self_healing_memory.json` — Learned UI patterns
