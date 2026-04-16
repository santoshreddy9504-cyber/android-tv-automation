#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║          NEXT-LEVEL QA INTELLIGENCE PLATFORM                        ║
║          Android TV / Fire TV OTT App Testing                       ║
╚══════════════════════════════════════════════════════════════════════╝

Unified entry point for all next-level capabilities:

  MODE 1: smart-monitor    — AI-powered silent monitoring
  MODE 2: multi-device     — Monitor all devices simultaneously
  MODE 3: chaos            — Run chaos engineering tests
  MODE 4: release-gate     — Evaluate build for release
  MODE 5: smoke            — Self-healing smoke test

Usage:
    python next_level.py --mode smart-monitor --ip 192.168.2.29 --app SouthStream
    python next_level.py --mode multi-device --duration 60
    python next_level.py --mode chaos --ip 192.168.2.29
    python next_level.py --mode release-gate
    python next_level.py --mode smoke --ip 192.168.2.29

Environment variables:
    ANTHROPIC_API_KEY   — Enables AI crash analysis (optional but powerful)
    SLACK_WEBHOOK_URL   — Enables Slack notifications
    SMTP_USER           — Gmail address for email alerts
    SMTP_PASSWORD       — Gmail app password
    EMAIL_TO            — Recipient email(s), comma-separated
"""

import argparse
import os
import signal
import sys
import threading
import time
import logging
import subprocess
from datetime import datetime
from typing import Optional

# ── Setup logging ─────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("next_level")


def print_banner():
    print("""
╔══════════════════════════════════════════════════════════════════════╗
║       NEXT-LEVEL QA INTELLIGENCE PLATFORM  v2.0                    ║
║       AI • Vision • Prediction • Multi-Device • Chaos               ║
╚══════════════════════════════════════════════════════════════════════╝
""")


# ── Argument parsing ──────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(
        description="Next-Level QA Intelligence Platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--mode", default="smart-monitor",
                   choices=["smart-monitor", "multi-device", "chaos", "release-gate", "smoke"],
                   help="Operation mode")
    p.add_argument("--ip", default="192.168.2.29", help="Primary device IP")
    p.add_argument("--port", type=int, default=5555)
    p.add_argument("--package", default="com.southstream.tv", help="App package name")
    p.add_argument("--app", default="SouthStream", help="App display name")
    p.add_argument("--duration", type=float, default=60.0, help="Duration in minutes (0=infinite)")
    p.add_argument("--api-key", default=None, help="Anthropic API key (or set ANTHROPIC_API_KEY)")
    p.add_argument("--slack-webhook", default=None, help="Slack webhook URL")
    p.add_argument("--email-to", default=None, help="Alert email address")
    p.add_argument("--dashboard-port", type=int, default=8080)
    p.add_argument("--no-dashboard", action="store_true")
    p.add_argument("--no-notifications", action="store_true")
    p.add_argument("--save-baseline", action="store_true", help="Save this run as release baseline")
    p.add_argument("--chaos-tests", nargs="*",
                   choices=["network_cut", "rapid_navigation",
                            "background_foreground", "kill_restart",
                            "low_memory", "network_throttle"],
                   help="Specific chaos tests to run (default: all)")
    p.add_argument("--debug", action="store_true")
    return p.parse_args()


# ── Mode: Smart Monitor ───────────────────────────────────────────────
def run_smart_monitor(args):
    """AI-powered monitoring with prediction, vision, and notifications."""
    from ai_engine.crash_analyzer import AICrashAnalyzer
    from ai_engine.ux_scorer import UXScorer
    from prediction.crash_predictor import CrashPredictor
    from vision.screen_analyzer import ScreenAnalyzer
    from notifications.notifier import NotificationManager, NotificationConfig
    from auto_bug.bug_reporter import BugReporter
    from dashboard.live_dashboard import LiveDashboard

    device_target = f"{args.ip}:{args.port}"
    print(f"\n  Device  : {device_target}")
    print(f"  Package : {args.package}")
    print(f"  App     : {args.app}")
    print(f"  Duration: {'infinite' if args.duration == 0 else f'{args.duration} min'}")

    # Initialize all AI modules
    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    analyzer = AICrashAnalyzer(api_key=api_key)
    predictor = CrashPredictor(crash_threshold_mb=420.0, warning_minutes=5.0)
    vision = ScreenAnalyzer()
    scorer = UXScorer()
    bug_reporter = BugReporter(device_target=device_target, package=args.package)

    # Notification setup
    notif_config = NotificationConfig(
        slack_webhook_url=args.slack_webhook or os.environ.get("SLACK_WEBHOOK_URL", ""),
        smtp_user=os.environ.get("SMTP_USER", ""),
        smtp_password=os.environ.get("SMTP_PASSWORD", ""),
        email_to=[e.strip() for e in (args.email_to or os.environ.get("EMAIL_TO", "")).split(",") if e.strip()],
        desktop_notifications=True,
        notify_on_prediction=True,
    )
    notifier = NotificationManager(notif_config if not args.no_notifications else None)

    # Live dashboard
    dashboard = LiveDashboard(port=args.dashboard_port)
    if not args.no_dashboard:
        dashboard.set_session_info(args.app, device_target, datetime.now().strftime("%Y%m%d_%H%M%S"))
        dashboard.start()

    # Connect ADB
    print(f"\n  Connecting to {device_target}...")
    result = subprocess.run(["adb", "connect", device_target], capture_output=True, text=True, timeout=15)
    if "connected" not in result.stdout.lower() and "already" not in result.stdout.lower():
        print(f"  ✗ Cannot connect: {result.stdout.strip()}")
        return

    print(f"  ✓ Connected\n")
    print("  Modules active:")
    print(f"    🤖 AI Crash Analysis  : {'Claude API' if analyzer.enabled else 'Rule-based fallback'}")
    print(f"    🔮 Crash Predictor    : Active (threshold 420MB)")
    print(f"    👁  Computer Vision   : Active")
    print(f"    📊 Live Dashboard     : {'http://localhost:' + str(args.dashboard_port) if not args.no_dashboard else 'Disabled'}")
    print(f"    🔔 Notifications      : {'Active' if not args.no_notifications else 'Disabled'}")
    print("\n  Monitoring... Press Ctrl+C to stop\n")

    stop_event = threading.Event()
    session_start = time.time()
    crash_count = 0
    logcat_lines = []
    memory_readings = []

    def adb_shell(cmd: str) -> str:
        try:
            r = subprocess.run(
                ["adb", "-s", device_target, "shell", cmd],
                capture_output=True, text=True, timeout=10,
            )
            return r.stdout.strip()
        except Exception:
            return ""

    def parse_memory(out: str) -> float:
        import re
        for line in out.splitlines():
            if "TOTAL" in line:
                nums = re.findall(r'\d+', line)
                if nums:
                    return int(nums[0]) / 1024
        return 0.0

    def parse_cpu(out: str) -> float:
        import re
        for line in out.splitlines():
            nums = re.findall(r'(\d+\.?\d*)%', line)
            if nums:
                return float(nums[0])
        return 0.0

    # ── Logcat reader thread ───────────────────────────────────────────
    import re
    crash_pattern = re.compile(
        r"FATAL EXCEPTION|AndroidRuntime.*Exception|ANR in|"
        r"Process.*has died|OutOfMemoryError|mqt_native_modules|"
        r"SIGSEGV|SIGABRT|Fatal signal",
        re.IGNORECASE,
    )

    def read_logcat():
        nonlocal crash_count
        try:
            proc = subprocess.Popen(
                ["adb", "-s", device_target, "logcat", "-v", "threadtime"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            )
            for line in proc.stdout:
                if stop_event.is_set():
                    break
                logcat_lines.append(line.rstrip())
                if len(logcat_lines) > 500:
                    logcat_lines.pop(0)

                if crash_pattern.search(line):
                    crash_count += 1
                    logger.warning(f"[Logcat] CRASH detected: {line.strip()[:100]}")

                    # AI analysis
                    analysis = analyzer.analyze(
                        logcat_lines=logcat_lines,
                        crash_title=line.strip()[:80],
                        crash_message=line.strip(),
                        app_name=args.app,
                        memory_mb=predictor.latest_prediction.current_memory_mb if predictor.latest_prediction else 0,
                        crash_count_today=crash_count,
                    )

                    # Notification
                    notifier.crash_detected(
                        title=analysis.title,
                        message=f"{analysis.what_happened}\n\nFix: {analysis.fix_suggestion[:100]}",
                        app=args.app,
                        device=device_target,
                        priority=analysis.priority,
                    )

                    # Auto bug report
                    bug = bug_reporter.create_from_crash(
                        crash_title=analysis.title,
                        crash_message=line.strip(),
                        logcat_lines=logcat_lines,
                        ai_analysis=analysis,
                        memory_mb=predictor.latest_prediction.current_memory_mb if predictor.latest_prediction else 0,
                        session_seconds=time.time() - session_start,
                        app_name=args.app,
                    )
                    bug_path = bug_reporter.export_html(bug)
                    logger.info(f"Bug report: {bug_path}")

                    # Dashboard
                    dashboard.report_crash(analysis.title, analysis.what_happened)

                    print(f"\n  ⚡ CRASH #{crash_count} DETECTED")
                    print(f"     {analysis.title} [{analysis.priority}]")
                    print(f"     {analysis.what_happened}")
                    print(f"     Fix: {analysis.fix_suggestion[:80]}")
                    print()

            proc.terminate()
        except Exception as exc:
            logger.error(f"Logcat thread error: {exc}")

    logcat_thread = threading.Thread(target=read_logcat, daemon=True)
    logcat_thread.start()

    # ── Performance poll loop ──────────────────────────────────────────
    screenshot_dir = "output/screenshots"
    os.makedirs(screenshot_dir, exist_ok=True)
    screenshot_count = 0

    def take_screenshot() -> Optional[str]:
        nonlocal screenshot_count
        screenshot_count += 1
        path = os.path.join(screenshot_dir, f"smart_monitor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        try:
            subprocess.run(
                ["adb", "-s", device_target, "exec-out", "screencap", "-p"],
                stdout=open(path, "wb"), timeout=10,
            )
            return path if os.path.exists(path) and os.path.getsize(path) > 1000 else None
        except Exception:
            return None

    interval = 30
    last_screenshot = 0

    try:
        while not stop_event.is_set():
            now = time.time()

            # Performance metrics
            mem_out = adb_shell(f"dumpsys meminfo {args.package}")
            mem_mb = parse_memory(mem_out)

            pid_out = adb_shell(f"pidof {args.package}")
            pid = pid_out.strip().split()[0] if pid_out.strip() else ""
            cpu = 0.0
            if pid:
                top_out = adb_shell(f"top -n 1 -p {pid}")
                cpu = parse_cpu(top_out)

            # Update predictor
            if mem_mb > 0:
                predictor.add_reading(mem_mb)
                prediction = predictor.predict()

                if prediction:
                    dashboard.update_prediction(
                        prediction.minutes_until_crash,
                        prediction.confidence,
                    )
                    if prediction.is_critical():
                        notifier.prediction_warning(
                            title=f"Crash in {prediction.minutes_until_crash:.1f} min",
                            message=prediction.summary(),
                            app=args.app,
                            device=device_target,
                        )

            # Dashboard update
            dashboard.update_performance(mem_mb, cpu)

            # Screenshot + vision analysis every 30s
            if now - last_screenshot >= interval:
                screenshot_path = take_screenshot()
                if screenshot_path:
                    screen_analysis = vision.analyze(screenshot_path)
                    if screen_analysis and screen_analysis.issues:
                        for issue in screen_analysis.issues:
                            dashboard.report_event(issue, f"Visual anomaly at {datetime.now().strftime('%H:%M:%S')}", level="warning")

                last_screenshot = now

            # Console status
            elapsed = int(now - session_start)
            mins, secs = divmod(elapsed, 60)
            mem_str = f"{mem_mb:.0f}MB" if mem_mb > 0 else "—"
            pred_str = ""
            if predictor.latest_prediction and predictor.latest_prediction.is_growing:
                mins_left = predictor.latest_prediction.minutes_until_crash
                if mins_left and mins_left < 15:
                    pred_str = f" | ⚠ crash in ~{mins_left:.1f}min"

            print(f"\r  [{mins:02d}:{secs:02d}] RAM:{mem_str} CPU:{cpu:.1f}% Crashes:{crash_count}{pred_str}   ", end="", flush=True)

            # Duration check
            if args.duration > 0 and elapsed >= args.duration * 60:
                print("\n\n  Duration reached. Stopping...")
                break

            stop_event.wait(timeout=interval)

    except KeyboardInterrupt:
        print("\n\n  Stopping...")
    finally:
        stop_event.set()

    # ── Final report ───────────────────────────────────────────────────
    duration_s = time.time() - session_start
    print(f"\n  Session complete: {duration_s/60:.1f} min | {crash_count} crashes | {screenshot_count} screenshots\n")

    # UX Score
    ux = scorer.score_session(
        session_id=datetime.now().strftime("%Y%m%d_%H%M%S"),
        app_name=args.app,
        duration_seconds=duration_s,
        crash_count=crash_count,
        restart_count=0,
        peak_memory_mb=predictor.latest_prediction.current_memory_mb if predictor.latest_prediction else 0,
        avg_cpu_percent=0,
        peak_frame_drop_pct=0,
    )
    print(f"  UX Score: {ux.score:.0f}/100 (Grade {ux.grade}) — {ux.verdict}")
    dashboard.update_ux_score(ux.score, ux.grade)

    # AI session summary
    summary = analyzer.get_session_summary()
    if summary:
        print(f"\n  AI Summary:")
        print(f"    Crashes analyzed: {summary.get('total_crashes_analyzed', 0)}")
        print(f"    P0 Critical: {summary.get('p0_critical', 0)}")
        print(f"    Easy fixes available: {summary.get('easy_fixes_available', 0)}")

    # Bug reports
    if bug_reporter.all_bugs:
        print(f"\n  Bug Reports: {len(bug_reporter.all_bugs)} created in output/bugs/")

    print()


# ── Mode: Multi-Device ────────────────────────────────────────────────
def run_multi_device(args):
    from multi_device.device_fleet import DeviceFleet
    from dashboard.live_dashboard import LiveDashboard

    dashboard = LiveDashboard(port=args.dashboard_port)
    if not args.no_dashboard:
        dashboard.set_session_info(args.app, "Multi-Device Fleet", "fleet")
        dashboard.start()

    fleet = DeviceFleet(duration_minutes=args.duration if args.duration > 0 else 9999)

    # Add configured devices — customize these
    fleet.add_device("Android TV", args.ip, args.package, device_type="android_tv")
    fleet.add_device("Fire TV", "192.168.2.8", args.package, device_type="fire_tv")

    print(f"\n  Starting multi-device fleet ({len(fleet._devices)} devices)...")
    print(f"  Duration: {args.duration} minutes\n")

    fleet.start()
    fleet.wait()

    # Generate and save report
    html = fleet.generate_report()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = f"output/reports/Fleet_Monitor_{ts}.html"
    os.makedirs("output/reports", exist_ok=True)
    with open(report_path, "w") as f:
        f.write(html)
    print(f"\n  Fleet report saved: {report_path}")
    print(f"  Total crashes across all devices: {fleet.total_crashes}")


# ── Mode: Chaos ───────────────────────────────────────────────────────
def run_chaos(args):
    from chaos.chaos_engineer import ChaosEngineer

    device_target = f"{args.ip}:{args.port}"
    print(f"\n  Chaos Engineering on {device_target}")
    print(f"  Package: {args.package}\n")

    chaos = ChaosEngineer(device_target=device_target, package=args.package)
    tests = args.chaos_tests  # None = all tests
    results = chaos.run_all(tests=tests)

    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    crashes = sum(1 for r in results if r.crash_occurred)

    print(f"\n  Chaos Results: {passed} passed / {failed} failed / {crashes} crashes")

    # Save HTML report
    html = f"""<!DOCTYPE html><html><head><title>Chaos Report</title>
    <style>body{{background:#0d0d1a;color:#f8f8f2;font-family:sans-serif;padding:20px;}}</style>
    </head><body><h1 style="color:#ff79c6;">Chaos Engineering Report</h1>
    <p style="color:#6272a4;">{datetime.now().strftime('%Y-%m-%d %H:%M')} | {device_target} | {args.package}</p>
    {chaos.generate_report(results)}</body></html>"""

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"output/reports/Chaos_{ts}.html"
    os.makedirs("output/reports", exist_ok=True)
    with open(path, "w") as f:
        f.write(html)
    print(f"  Report saved: {path}")


# ── Mode: Release Gate ────────────────────────────────────────────────
def run_release_gate(args):
    from release_gate.release_gate import ReleaseGate, BuildMetrics

    gate = ReleaseGate()
    has_baseline = gate.load_baseline()

    if not has_baseline and not args.save_baseline:
        print("\n  No baseline found. Run with --save-baseline on a known-good build first.")
        print("  Example: python next_level.py --mode release-gate --save-baseline\n")

    # Create metrics from most recent session (placeholder — integrate with real session)
    import random
    current = BuildMetrics(
        build_id=f"build-{datetime.now().strftime('%Y%m%d-%H%M')}",
        timestamp=datetime.now(),
        app_name=args.app,
        crash_count=0,
        crash_rate_per_hour=0.0,
        peak_memory_mb=280.0,
        pass_rate=85.0,
    )

    if args.save_baseline:
        gate.save_baseline(current)
        print(f"\n  Baseline saved: {current.build_id}")
        return

    verdict = gate.evaluate(current)
    html_content = verdict.to_html()

    print(f"\n  Release Gate: {verdict.decision}")
    print(f"  {verdict.summary}")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"output/reports/ReleaseGate_{ts}.html"
    os.makedirs("output/reports", exist_ok=True)
    with open(path, "w") as f:
        f.write(f"<!DOCTYPE html><html><head><title>Release Gate</title>"
                f"<style>body{{background:#0d0d1a;color:#f8f8f2;font-family:sans-serif;padding:20px;}}</style>"
                f"</head><body>{html_content}</body></html>")
    print(f"  Report saved: {path}")


# ── Mode: Self-Healing Smoke Test ─────────────────────────────────────
def run_smoke(args):
    from automation.self_healing_runner import SelfHealingRunner

    device_target = f"{args.ip}:{args.port}"
    print(f"\n  Self-Healing Smoke Test on {device_target}")
    print(f"  Package: {args.package}\n")

    subprocess.run(["adb", "connect", device_target], capture_output=True, timeout=15)

    runner = SelfHealingRunner(device_target=device_target, package=args.package)
    results = runner.run_smoke_test()

    print(f"\n  Results: {sum(1 for r in results if r.success)}/{len(results)} passed")
    print(f"  Auto-healed: {sum(1 for r in results if r.healed)}")
    print(f"  Pass rate: {runner.pass_rate:.1f}%\n")

    for r in results:
        status = "✅" if r.success else "❌"
        healed = " (HEALED)" if r.healed else ""
        print(f"    {status} {r.intent_name}{healed} — {r.duration_seconds:.1f}s")

    html = f"""<!DOCTYPE html><html><head><title>Smoke Test</title>
    <style>body{{background:#0d0d1a;color:#f8f8f2;font-family:sans-serif;padding:20px;}}</style>
    </head><body><h1 style="color:#50fa7b;">Self-Healing Smoke Test</h1>
    <p style="color:#6272a4;">{datetime.now().strftime('%Y-%m-%d %H:%M')} | {device_target}</p>
    {runner.generate_healing_report()}</body></html>"""

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"output/reports/SmokeTest_{ts}.html"
    os.makedirs("output/reports", exist_ok=True)
    with open(path, "w") as f:
        f.write(html)
    print(f"\n  Report saved: {path}")


# ── Main ──────────────────────────────────────────────────────────────
def main():
    args = parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    print_banner()

    modes = {
        "smart-monitor":  run_smart_monitor,
        "multi-device":   run_multi_device,
        "chaos":          run_chaos,
        "release-gate":   run_release_gate,
        "smoke":          run_smoke,
    }

    runner = modes.get(args.mode)
    if not runner:
        print(f"Unknown mode: {args.mode}")
        sys.exit(1)

    print(f"  Mode: {args.mode.upper()}")
    runner(args)


if __name__ == "__main__":
    main()
