#!/usr/bin/env python3
"""
QA Engine v2.1 — Universal Android App Testing Tool
====================================================
Works with ANY Android / Android TV app.

Usage:
  python3 qaengine.py --device 192.168.2.8:5555 --app in.southstream.android
  python3 qaengine.py --device 192.168.2.8:5555 --app com.hotstar.android --record
  python3 qaengine.py --device 192.168.2.8:5555 --app in.southstream.android \\
          --compare sessions/southstream_20260414 \\
          --webhook https://hooks.slack.com/services/xxx

Fully automatic — everything happens in background:
  ✓ Screenshots every 2 min + on every crash / critical memory
  ✓ Crash detection + 9-step AI analysis (instant)
  ✓ Adaptive memory baseline (learn first 2 min)
  ✓ CPU monitoring
  ✓ Battery drain tracking
  ✓ Memory leak detection (linear slope)
  ✓ Crash recovery timing
  ✓ Auto reconnect if device drops
  ✓ Keypress logging (steps to reproduce)
  ✓ Screen detection (current Activity)
  ✓ Network / ANR / Focus / Frame drop monitoring
  ✓ Build comparison vs previous session
  ✓ Webhook alerts on crash / ANR
  ✓ Live status line every 60s
  ✓ Full HTML report + CSV export on Ctrl+C
"""

import sys, os, time, argparse, signal, json
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from core.adb      import ADB
from core.monitor  import UniversalMonitor, compare_builds
from core.recorder import ScreenRecorder
from core.reporter import generate_report
from ai.analyzer   import QAThinkingEngine


def parse_args():
    p = argparse.ArgumentParser(description="QA Engine — Universal Android App Tester")
    p.add_argument("--device",  required=True,
                   help="Device IP:port  e.g. 192.168.2.8:5555")
    p.add_argument("--app",     required=True,
                   help="Package name   e.g. in.southstream.android")
    p.add_argument("--record",  action="store_true",
                   help="Enable screen recording")
    p.add_argument("--compare", default=None,
                   help="Previous session dir for build comparison")
    p.add_argument("--webhook", default=None,
                   help="Webhook URL for crash/ANR alerts (Slack, Teams, etc.)")
    p.add_argument("--out",     default=None,
                   help="Output folder (auto-created if not set)")
    return p.parse_args()


class QASession:

    def __init__(self, args):
        self.package     = args.app
        self.device      = args.device
        self.do_rec      = args.record
        self.compare_dir = args.compare
        self.webhook_url = args.webhook

        ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
        pkg_short = self.package.split(".")[-1]
        self.session_dir = args.out or os.path.join(ROOT, "sessions", f"{pkg_short}_{ts}")
        os.makedirs(self.session_dir, exist_ok=True)

        self.adb      = ADB(self.device)
        self.monitor  = UniversalMonitor(self.adb, self.package,
                                         session_dir=self.session_dir,
                                         memory_interval=20,
                                         screenshot_interval=120)
        self.recorder = ScreenRecorder(
            self.adb,
            out_dir=os.path.join(self.session_dir, "recordings")
        ) if self.do_rec else None

        self.engine          = QAThinkingEngine()
        self._analyses_html  = []
        self._alerts_html    = []
        self._device_info    = {}
        self._app_version    = {}
        self._baseline_shown = False
        self._prev_summary   = None

    # ── Start ────────────────────────────────────────────────────────────────

    def start(self):
        self._print_banner()

        # Connect
        if not self.adb.connect():
            print(f"  ✗ Cannot connect to {self.device}")
            print(f"    Run:  adb connect {self.device}")
            sys.exit(1)

        self.adb.wake_screen()
        self._device_info = self.adb.get_device_info()
        self._app_version = self.adb.get_app_version(self.package)

        # Auto-launch if app not running
        pid = self.adb.get_pid(self.package)
        if not pid:
            print(f"  App not running — launching {self.package}...")
            self.adb.launch_app(self.package)
            time.sleep(3)

        # Load previous session for comparison
        self._prev_summary = self._load_prev_summary()

        print(f"  Device  : {self._device_info.get('brand','')} {self._device_info.get('model','')}")
        print(f"  Android : {self._device_info.get('android','?')} (SDK {self._device_info.get('sdk','?')})")
        print(f"  App     : {self.package} v{self._app_version.get('name','?')} (build {self._app_version.get('code','?')})")
        print(f"  AI      : {'Claude API' if self.engine.ai_enabled else 'Rule Engine (offline)'}")
        print(f"  Record  : {'ON' if self.do_rec else 'OFF'}")
        print(f"  Webhook : {self.webhook_url or 'OFF'}")
        if self._prev_summary:
            print(f"  Compare : {self.compare_dir}  "
                  f"(crashes={self._prev_summary.get('crashes',0)}, "
                  f"score={self._prev_summary.get('qa_score','?')}/100)")
        print(f"  Output  : {self.session_dir}")
        print(f"\n{'─'*58}")
        print(f"  ✓ Monitoring started. Test your app now.")
        print(f"  ✓ Learning memory baseline for first 2 min...")
        print(f"  Press  Ctrl+C  when done to get the report.")
        print(f"{'─'*58}\n")

        # Wire events
        self.monitor.on_event(self._on_event)
        self.monitor.start()

        if self.recorder:
            self.recorder.start()
            self._log("🎥 Screen recording started")

        # First screenshot
        self.monitor.take_screenshot("session_start")

        # Handle Ctrl+C
        signal.signal(signal.SIGINT, self._on_stop)

        # Live status line every 60 seconds
        import threading
        threading.Thread(target=self._status_loop, daemon=True).start()

        # Stay alive
        try:
            while True:
                time.sleep(1)
        except SystemExit:
            pass

    # ── Live Status Line ─────────────────────────────────────────────────────

    def _status_loop(self):
        """Print a live status summary every 60 seconds."""
        time.sleep(60)
        while True:
            try:
                elapsed = int(time.time() - self.monitor._start_time)
                mins    = elapsed // 60
                secs    = elapsed % 60
                score   = self.monitor._compute_qa_score()
                score_c = "✅" if score >= 80 else "⚠️" if score >= 50 else "❌"
                print(
                    f"\n  ─── STATUS [{mins}m{secs:02d}s] ───  "
                    f"Score:{score_c}{score}  "
                    f"Crashes:{self.monitor._crash_count}  "
                    f"RAM:{self.monitor._last_mem:.0f}MB  "
                    f"CPU:{self.monitor._last_cpu:.0f}%  "
                    f"Screen:{self.monitor._current_screen}  "
                    f"Net:{self.monitor._net_fails}"
                )
            except:
                pass
            time.sleep(60)

    # ── Event handler ─────────────────────────────────────────────────────────

    def _on_event(self, event):
        icons = {
            "CRASH":      "💥",
            "MEMORY":     "🔴" if "CRITICAL" in event.message or "LEAK" in event.message else "🟠",
            "PERF":       "⚡",
            "ANR":        "🚨",
            "NETWORK":    "🌐",
            "CONTENT":    "⚠️",
            "FOCUS":      "🎯",
            "SCREENSHOT": "📸",
            "INFO":       "  ",
            "LOG":        "  ",
        }
        icon = icons.get(event.type, "  ")

        screen_tag = ""
        if event.type in ("CRASH", "MEMORY", "ANR", "NETWORK", "CONTENT", "FOCUS", "PERF"):
            screen = self.monitor._current_screen
            if screen and screen != "Unknown":
                screen_tag = f"  [{screen}]"

        print(f"  {icon} [{event.timestamp.strftime('%H:%M:%S')}] {event.message}{screen_tag}")

        # Print baseline once when established
        if event.type == "INFO" and "Baseline memory set:" in event.message and not self._baseline_shown:
            self._baseline_shown = True
            b = self.monitor._baseline_mem
            print(f"  ✅ Baseline: {b}MB  |  Alert at: {b*1.5:.0f}MB (warn) / {b*2:.0f}MB (critical)")

        # Auto crash analysis
        if event.type == "CRASH":
            self._analyze_crash(event)
            self._send_webhook("CRASH", event.message)

        elif event.type in ("CONTENT", "ANR", "NETWORK"):
            self._quick_alert(event)
            if event.type == "ANR":
                self._send_webhook("ANR", event.message)

    # ── Auto crash analysis ───────────────────────────────────────────────────

    def _analyze_crash(self, event):
        if event.data.get("duplicate"):
            return

        self._log("🤖 Analyzing crash...")

        log_lines = self._read_logcat(100)
        analysis  = self.engine.auto_analyze(
            logcat        = log_lines,
            crash_message = event.message,
            user_action   = f"Manual testing on screen: {event.data.get('screen', 'Unknown')}",
            screen        = event.data.get("screen", "Unknown — check last screenshot"),
            memory_mb     = event.data.get("mem_mb", self.monitor._last_mem),
            app_name      = self.package,
        )

        print(analysis.to_text())
        self._analyses_html.append(analysis.to_html())

        crash_num = event.data.get("crash_num", self.monitor._crash_count)
        txt_path  = os.path.join(self.session_dir, f"analysis_crash{crash_num}.txt")
        with open(txt_path, "w") as f:
            f.write(analysis.to_text())

        steps = event.data.get("steps", [])
        if steps:
            print(f"\n  Steps before crash:")
            for i, s in enumerate(steps, 1):
                print(f"    {i}. {s}")
            print()

    # ── Auto alert for non-crash issues ──────────────────────────────────────

    def _quick_alert(self, event):
        log_lines = self._read_logcat(30)
        alert = self.engine.manual_alert(
            action    = f"Testing on screen: {self.monitor._current_screen}",
            screen    = self.monitor._current_screen,
            logcat    = log_lines,
            memory_mb = self.monitor._last_mem,
        )
        print(alert.to_text())
        self._alerts_html.append(alert.to_html())

    # ── Webhook ───────────────────────────────────────────────────────────────

    def _send_webhook(self, event_type: str, message: str):
        if not self.webhook_url:
            return
        try:
            import urllib.request, json as _json
            payload = _json.dumps({
                "text": (
                    f"*QA Engine Alert* — {event_type}\n"
                    f"App: `{self.package}`\n"
                    f"Device: {self._device_info.get('brand','')} {self._device_info.get('model','')}\n"
                    f"Screen: {self.monitor._current_screen}\n"
                    f"RAM: {self.monitor._last_mem}MB\n"
                    f"Message: {message}"
                )
            }).encode()
            req = urllib.request.Request(
                self.webhook_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            urllib.request.urlopen(req, timeout=5)
            self._log(f"📨 Webhook sent: {event_type}")
        except Exception as e:
            self._log(f"⚠️  Webhook failed: {e}")

    # ── Stop + report ─────────────────────────────────────────────────────────

    def _on_stop(self, sig=None, frame=None):
        print(f"\n\n{'─'*58}")
        print(f"  Stopping session...")

        self.monitor.stop()

        recordings = []
        if self.recorder:
            recordings = self.recorder.stop()
            self._log(f"🎥 {len(recordings)} recording(s) saved")

        # Final screenshot
        self.monitor.take_screenshot("session_end")

        # Get summary
        summary = self.monitor.summary()
        summary["app_version"] = self._app_version

        # Save summary JSON for future --compare
        self._save_summary(summary)

        # Build comparison
        compare_data = None
        if self._prev_summary:
            compare_data = compare_builds(
                self._prev_summary, summary,
                label_a=f"Prev ({os.path.basename(self.compare_dir)})",
                label_b=f"Current ({datetime.now().strftime('%b %d')})",
            )

        # Generate report
        self._log("📊 Generating report...")
        out_path = generate_report(
            session_dir        = self.session_dir,
            app_name           = self.package.split(".")[-1].title(),
            package            = self.package,
            device_info        = self._device_info,
            app_version        = self._app_version,
            summary            = summary,
            analyses_html      = self._analyses_html,
            manual_alerts_html = self._alerts_html,
            recordings         = recordings,
            compare_data       = compare_data,
        )

        # Print final summary
        screens_visited = summary.get("screens_visited", [])
        score           = summary.get("qa_score", 0)
        score_label     = "EXCELLENT" if score >= 90 else "GOOD" if score >= 70 else \
                          "NEEDS WORK" if score >= 50 else "CRITICAL"
        score_icon      = "✅" if score >= 70 else "⚠️" if score >= 50 else "❌"

        print(f"\n{'─'*58}")
        print(f"  ✅  SESSION COMPLETE")
        print(f"{'─'*58}")
        print(f"  QA Score      : {score_icon} {score}/100 — {score_label}")
        print(f"  Duration      : {summary['duration_str']}")
        print(f"  Crashes       : {summary['crashes']} ({summary['unique_crashes']} unique)")
        print(f"  ANRs          : {summary['anrs']}")
        print(f"  Net errors    : {summary['net_failures']}")
        print(f"  Focus issues  : {summary['focus_issues']}")
        print(f"  Frame drops   : {summary['frame_drops']}")
        print(f"  Memory leak   : {'YES ⚠️' if summary['leak_detected'] else 'No'}")
        print(f"  Peak RAM      : {summary['peak_mem_mb']}MB  (baseline {summary['baseline_mem_mb']}MB)")
        print(f"  Peak CPU      : {summary['peak_cpu']}%  (avg {summary['avg_cpu']}%)")
        print(f"  Battery       : {summary['battery_start']}% → {summary['battery_end']}%  "
              f"({summary['battery_drain']}% drain, {summary['drain_per_hour']}%/hr)")
        if summary['recovery_times']:
            print(f"  Crash recovery: avg {summary['avg_recovery_sec']}s")
        print(f"  Screens seen  : {len(screens_visited)}  "
              f"{' → '.join(screens_visited[:6])}{'...' if len(screens_visited)>6 else ''}")
        print(f"  Screenshots   : {summary['screenshots']}")
        print(f"  Recordings    : {len(recordings)}")
        if compare_data:
            oc = {"IMPROVED":"✅","REGRESSED":"❌","SAME":"➡️"}.get(compare_data["overall"],"")
            print(f"  Build Delta   : {oc} {compare_data['overall']} vs previous build")
        print(f"  Report        : {out_path}")
        print(f"{'─'*58}\n")

        os.system(f"open '{out_path}' 2>/dev/null")
        sys.exit(0)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _read_logcat(self, lines: int = 100):
        path = os.path.join(self.session_dir, "logcat.txt")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return f.readlines()[-lines:]

    def _log(self, msg: str):
        print(f"  {msg}")

    def _save_summary(self, summary: dict):
        path = os.path.join(self.session_dir, "summary.json")
        save = {k: v for k, v in summary.items()
                if k not in ("timeline", "mem_samples", "cpu_samples", "events")}
        try:
            with open(path, "w") as f:
                json.dump(save, f, indent=2)
        except Exception as e:
            self._log(f"Warning: could not save summary.json — {e}")

    def _load_prev_summary(self) -> dict:
        if not self.compare_dir:
            return None
        path = os.path.join(self.compare_dir, "summary.json")
        if not os.path.exists(path):
            alt = os.path.join(ROOT, "sessions", self.compare_dir, "summary.json")
            if os.path.exists(alt):
                path = alt
            else:
                print(f"  ⚠️  --compare: summary.json not found in {self.compare_dir}")
                return None
        try:
            with open(path) as f:
                return json.load(f)
        except Exception as e:
            print(f"  ⚠️  --compare: could not load summary — {e}")
            return None

    def _print_banner(self):
        print(f"""
{'='*58}
   QA ENGINE v2.1  —  Universal Android App Tester
   12 Features: Screen · Network · Adaptive RAM · CPU
   Battery · Leak Detection · Recovery · Dedup
   Focus · Steps · Build Compare · Webhook · CSV
{'='*58}""")


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args    = parse_args()
    session = QASession(args)
    session.start()
