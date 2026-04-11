#!/usr/bin/env python3
"""
Android TV OTT Automation & Monitoring System
=============================================
Entry point — configures and launches a full monitoring session.

Usage:
    python main.py [--ip 192.168.1.100] [--package com.example.app]
                   [--duration 2.5] [--no-dashboard] [--web] [--debug]
"""

import argparse
import queue as _queue
import signal
import sys
import threading
import logging

from utils.logger import setup_logging
from utils.helpers import check_adb_installed, get_adb_version, ensure_output_dirs, print_banner
from config import config

# Import all components
from core.session_manager import SessionManager
from models.events import IssueCategory
from models.test_results import TestSuite
from monitors.logcat_monitor import LogcatMonitor, register_timing_monitor
from monitors.performance_monitor import PerformanceMonitor
from monitors.timing_monitor import TimingMonitor
from handlers.alert_handler import AlertHandler
from handlers.screenshot_handler import ScreenshotHandler
from handlers.log_handler import LogHandler, register_logcat_monitor
from handlers.notifier import NotifierHandler
from handlers.test_report_handler import TestReportHandler
from dashboard.cli_dashboard import CLIDashboard
from dashboard.web_dashboard import WebDashboard

logger = logging.getLogger(__name__)

# Global test suite — accessible for report generation
_test_suite: TestSuite = None
_timing_mon: TimingMonitor = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Android TV OTT Automation & Monitoring System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--ip",      default=None, help=f"Android TV IP (default: {config.device.device_ip})")
    parser.add_argument("--port",    type=int, default=None, help=f"ADB port (default: {config.device.adb_port})")
    parser.add_argument("--package", default=None, help=f"App package (default: {config.app.package_name})")
    parser.add_argument("--duration",type=float, default=None, help="Session hours (0=infinite)")
    parser.add_argument("--no-restart",    action="store_true", help="Disable crash auto-restart")
    parser.add_argument("--no-dashboard",  action="store_true", help="Disable CLI dashboard")
    parser.add_argument("--web",           action="store_true", help="Enable web dashboard :8080")
    parser.add_argument("--web-port",      type=int, default=None)
    parser.add_argument("--no-screenshots",action="store_true")
    parser.add_argument("--no-sound",      action="store_true")
    parser.add_argument("--debug",         action="store_true", help="Verbose logging")
    return parser.parse_args()


def apply_args(args: argparse.Namespace):
    if args.ip:              config.device.device_ip = args.ip
    if args.port:            config.device.adb_port = args.port
    if args.package:         config.app.package_name = args.package
    if args.duration is not None: config.monitor.session_duration_hours = args.duration
    if args.no_restart:      config.app.crash_restart_enabled = False
    if args.no_dashboard:    config.dashboard.cli_dashboard_enabled = False
    if args.web:             config.dashboard.web_dashboard_enabled = True
    if args.web_port:        config.dashboard.web_port = args.web_port
    if args.no_screenshots:  config.alert.capture_screenshot_on_issue = False
    if args.no_sound:        config.alert.sound_alerts_enabled = False


def preflight_checks() -> bool:
    print("\n[Preflight] Checking prerequisites ...")
    if not check_adb_installed():
        print("  ✗  adb not found. Install Android SDK Platform Tools.")
        return False
    print(f"  ✓  {get_adb_version()}")
    print(f"  ✓  Target device : {config.device.adb_target}")
    print(f"  ✓  Package       : {config.app.package_name}")
    dur = config.monitor.session_duration_hours
    print(f"  ✓  Duration      : {'infinite' if dur == 0 else f'{dur}h'}")
    return True


def build_session() -> SessionManager:
    global _test_suite, _timing_mon

    session = SessionManager()

    # ── Test suite (shared with timing monitor + report) ─────────────────
    _test_suite = TestSuite(
        session_id=session.session_id,
        app_package=config.app.package_name,
    )

    # ── Monitors ─────────────────────────────────────────────────────────
    logcat_mon = LogcatMonitor(session)
    perf_mon   = PerformanceMonitor(session)
    _timing_mon = TimingMonitor(_test_suite)

    # Register timing monitor with logcat stream
    register_timing_monitor(_timing_mon)
    register_logcat_monitor(logcat_mon)

    session.register_monitor(logcat_mon)
    session.register_monitor(perf_mon)

    # ── Handlers ─────────────────────────────────────────────────────────
    screenshot_handler = ScreenshotHandler()
    log_handler        = LogHandler()
    alert_handler      = AlertHandler()
    notifier           = NotifierHandler()

    # Order: screenshot + log first so paths are attached before alert prints
    session.register_handler(screenshot_handler)
    session.register_handler(log_handler)
    session.register_handler(alert_handler)
    session.register_handler(notifier)

    # ── Dashboards ───────────────────────────────────────────────────────
    cli_dash = CLIDashboard(session)
    web_dash = WebDashboard(session)

    # Patch dispatch to also feed dashboards and handle crash restarts
    def _patched_dispatch():
        while not session.stop_event.is_set() or not session.event_queue.empty():
            try:
                event = session.event_queue.get(timeout=1.0)
            except _queue.Empty:
                continue

            session.stats.record_event(event)

            for handler in session._handlers:
                try:
                    handler.handle(event, session.adb)
                except Exception as exc:
                    logger.error(f"Handler {handler.__class__.__name__} error: {exc}")

            cli_dash.on_event(event)
            web_dash.on_event(event)

            if event.category == IssueCategory.CRASH:
                t = threading.Thread(
                    target=session._handle_crash_restart,
                    args=(event,), daemon=True,
                )
                t.start()

            session.event_queue.task_done()

    session._dispatch_events = _patched_dispatch
    session.set_dashboard(cli_dash)

    if config.dashboard.web_dashboard_enabled:
        t = threading.Thread(target=web_dash.run, name="WebDashboard", daemon=True)
        t.start()

    return session


def main():
    args = parse_args()
    apply_args(args)

    import uuid
    session_id = str(uuid.uuid4())[:8]
    setup_logging(level="DEBUG" if args.debug else "INFO", session_id=session_id)
    ensure_output_dirs()

    print_banner()

    if not preflight_checks():
        sys.exit(1)

    print("\n[Setup] Building monitoring session ...")
    session = build_session()

    def _signal_handler(sig, frame):
        print("\n\n[Signal] Stopping session gracefully ...")
        session.stop()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    print("[Setup] Starting session ...\n")

    try:
        session.start()
    finally:
        _generate_report(session)


def _generate_report(session: SessionManager):
    global _test_suite, _timing_mon

    print("\n[Report] Finalising test data ...")

    if _timing_mon:
        _timing_mon.finalize()

    if _test_suite:
        from datetime import datetime
        _test_suite.end_time = datetime.now()

    print("[Report] Generating QA test report ...")
    report = TestReportHandler()
    html_path = report.generate(_test_suite, session.stats)
    if html_path:
        print(f"[Report] ✅ Report saved: {html_path}")

    _print_summary(session)


def _print_summary(session: SessionManager):
    from utils.helpers import human_duration
    stats = session.stats
    suite = _test_suite

    print("\n" + "=" * 65)
    print(f"  QA TEST SUMMARY — {config.app.app_name}")
    print("=" * 65)
    print(f"  Session ID    : {stats.session_id}")
    print(f"  Duration      : {human_duration(stats.duration_seconds)}")
    print(f"  Peak CPU      : {stats.peak_cpu:.1f}%")
    print(f"  Peak Memory   : {stats.peak_memory_mb:.0f} MB")
    print(f"  Crashes       : {stats.crash_count}")
    print(f"  Auto-restarts : {stats.restart_count}")

    if suite:
        print(f"\n  ── Test Results ────────────────────────────────")
        print(f"  Tests Run     : {suite.total}")
        print(f"  Passed        : {suite.passed}  ✅")
        print(f"  Slow          : {suite.slow}   ⚠️")
        print(f"  Failed        : {suite.failed}  ❌")
        print(f"  Pass Rate     : {suite.pass_rate:.1f}%")
        print(f"  Avg Load Time : {suite.avg_load_ms:.0f} ms")
        print(f"  Buffering     : {suite.buffering_count} events "
              f"({suite.total_buffering_ms/1000:.1f}s total)")

    if stats.issues_by_category:
        print(f"\n  ── Issues Detected ─────────────────────────────")
        for cat, count in sorted(stats.issues_by_category.items()):
            print(f"    {cat:<14} {count}")

    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
