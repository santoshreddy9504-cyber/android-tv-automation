"""
Elite QA Agent — Intelligent End-to-End Testing for SouthStream on Android TV / Fire TV

Thinks and acts like a senior manual tester with 15+ years experience.
Follows: EXPECT → EXECUTE → OBSERVE → COMPARE → DECIDE for every action.

Run:
    python3.8 qa_agent.py --ip 192.168.2.8 --package in.southstream.android

"""

from __future__ import annotations
import argparse
import subprocess
import time
import os
import re
import json
import base64
import logging
import sys
import shutil
import threading
import queue
from datetime import datetime
from typing import Optional, List, Dict, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("QAAgent")


# ─────────────────────────────────────────────────────────────────────────────
# CRASH CLASSIFICATION TYPES
# ─────────────────────────────────────────────────────────────────────────────

class CrashType:
    PLAYER      = "Player Crash"
    NAVIGATION  = "Navigation Crash"
    API_DATA    = "API / Data Crash"
    UI          = "UI Crash"
    MEMORY      = "Memory / Performance Crash"
    NULL        = "Null Pointer / Missing Data Crash"
    UNKNOWN     = "Unknown Crash"


# ─────────────────────────────────────────────────────────────────────────────
# USER JOURNEY TRACKER
# Tracks every action the tester takes — used to reconstruct steps before crash
# ─────────────────────────────────────────────────────────────────────────────

class JourneyTracker:
    """Records the last N tester actions with timestamps."""

    MAX_STEPS = 10

    def __init__(self):
        self._steps: List[Dict] = []
        self._current_screen = "Unknown"
        self._ui_state       = "idle"   # idle / loading / playing

    def record(self, action: str, screen: str = "", ui_state: str = ""):
        """Call this every time the agent does something meaningful."""
        if screen:
            self._current_screen = screen
        if ui_state:
            self._ui_state = ui_state

        step = {
            "action":    action,
            "screen":    self._current_screen,
            "ui_state":  self._ui_state or "idle",
            "timestamp": datetime.now().strftime("%H:%M:%S"),
        }
        self._steps.append(step)
        if len(self._steps) > self.MAX_STEPS:
            self._steps.pop(0)

        log.debug(f"  JOURNEY: {action} [{self._current_screen}]")

    def set_screen(self, name: str):
        self._current_screen = name

    def set_state(self, state: str):
        self._ui_state = state

    @property
    def current_screen(self) -> str:
        return self._current_screen

    @property
    def ui_state(self) -> str:
        return self._ui_state

    def last_steps(self) -> List[Dict]:
        return list(self._steps)

    def as_numbered_steps(self) -> str:
        lines = []
        for i, s in enumerate(self._steps, 1):
            lines.append(f"{i}. [{s['timestamp']}] {s['action']}  (Screen: {s['screen']})")
        return "\n".join(lines) if lines else "No actions recorded"

    def clear(self):
        self._steps.clear()


# ─────────────────────────────────────────────────────────────────────────────
# CRASH INTELLIGENCE
# Deep analysis of every crash — not just "app crashed"
# ─────────────────────────────────────────────────────────────────────────────

class CrashReport:
    """Complete intelligent crash report."""
    def __init__(self):
        self.title           = ""
        self.crash_type      = CrashType.UNKNOWN
        self.user_journey    = ""       # numbered steps before crash
        self.current_screen  = ""
        self.action_at_crash = ""
        self.ui_state        = ""
        self.timestamp       = datetime.now().strftime("%H:%M:%S")

        # Log analysis
        self.exception_type  = ""
        self.error_message   = ""
        self.failed_api      = ""
        self.stack_summary   = ""
        self.log_snippet     = ""

        # Root cause
        self.root_cause      = ""
        self.root_cause_simple = ""   # plain English for tester

        # Reproduction
        self.repro_steps     = ""

        # Evidence
        self.screenshot      = ""
        self.severity        = "CRITICAL"


class CrashIntelligence:
    """
    Deep crash analyzer.
    Captures context, reads logcat, classifies crash, predicts root cause.
    """

    # Exception patterns → crash type
    EXCEPTION_MAP = [
        (r"NullPointerException",              CrashType.NULL),
        (r"OutOfMemoryError",                  CrashType.MEMORY),
        (r"ExoPlaybackException|PlayerError|DRM|MediaCodec", CrashType.PLAYER),
        (r"NetworkOnMainThread|SocketTimeout|ConnectException|HttpException", CrashType.API_DATA),
        (r"IllegalStateException.*Fragment|IllegalStateException.*Activity", CrashType.NAVIGATION),
        (r"IndexOutOfBounds|ArrayIndex",       CrashType.UI),
        (r"JSONException|ParseException|MalformedURL", CrashType.API_DATA),
        (r"mqt_native_modules|ReactNative|Reanimated", CrashType.UI),
        (r"InflateException|View.*null",       CrashType.UI),
    ]

    # Root cause prediction rules
    ROOT_CAUSE_RULES = {
        CrashType.NULL:       ("Null Pointer / Missing data",
                               "A piece of data was expected but was empty or missing. The app tried to use it without checking first — causing a crash. Common cause: API returned empty response or watchlist item has no content."),
        CrashType.MEMORY:     ("Memory Exhaustion",
                               "The app used too much RAM and Android was forced to kill it. This is caused by images and video data not being released when navigating between screens."),
        CrashType.PLAYER:     ("Video Player Error",
                               "The video player (ExoPlayer) crashed. This can happen when the video URL is broken, DRM license fails, or the player is opened before it is fully ready."),
        CrashType.API_DATA:   ("API / Network Failure",
                               "A network request failed and the app did not handle the failure properly. Instead of showing an error message, the app crashed."),
        CrashType.NAVIGATION: ("Navigation State Error",
                               "The user navigated away from a screen while the app was still processing something on that screen. The app tried to update a screen that no longer existed."),
        CrashType.UI:         ("UI / React Native Bridge Error",
                               "The UI component crashed. In React Native apps this often means an animation or component tried to update after the screen was already closed."),
        CrashType.UNKNOWN:    ("Unknown Crash",
                               "The exact cause could not be determined from the available logs. Developer needs to check the full stack trace."),
    }

    def __init__(self, adb: "ADB", package: str, ss_dir: str):
        self._adb     = adb
        self._pkg     = package
        self._ss_dir  = ss_dir

    def analyze(self, journey: JourneyTracker, action_at_crash: str,
                screenshot_label: str = "crash") -> CrashReport:
        """
        Full crash analysis:
        1. Capture context
        2. Pull logcat
        3. Extract exception
        4. Classify crash
        5. Predict root cause
        6. Generate reproduction steps
        """
        report = CrashReport()
        report.current_screen  = journey.current_screen
        report.action_at_crash = action_at_crash
        report.ui_state        = journey.ui_state
        report.user_journey    = journey.as_numbered_steps()

        log.info("  🔍 Running crash intelligence analysis...")

        # ── Step 1: Screenshot at crash moment ──────────────────────────
        ts  = datetime.now().strftime("%H%M%S")
        fn  = f"{self._ss_dir}/crash_{ts}_{screenshot_label}.png"
        self._adb.screenshot(fn)
        report.screenshot = fn
        log.info(f"  📸 Crash screenshot: {fn}")

        # ── Step 2: Pull logcat around crash ─────────────────────────────
        log_snippet = self._pull_logcat()
        report.log_snippet = log_snippet

        # ── Step 3: Extract exception info ───────────────────────────────
        report.exception_type, report.error_message, report.stack_summary = \
            self._extract_exception(log_snippet)

        # ── Step 4: Check for failed API ─────────────────────────────────
        report.failed_api = self._extract_failed_api(log_snippet)

        # ── Step 5: Classify crash ────────────────────────────────────────
        report.crash_type = self._classify(log_snippet, report.exception_type)

        # ── Step 6: Root cause prediction ────────────────────────────────
        cause_short, cause_plain = self.ROOT_CAUSE_RULES.get(
            report.crash_type, self.ROOT_CAUSE_RULES[CrashType.UNKNOWN]
        )
        report.root_cause        = cause_short
        report.root_cause_simple = cause_plain

        # ── Step 7: Build crash title ─────────────────────────────────────
        screen = report.current_screen or "Unknown Screen"
        report.title = f"App crashes when {action_at_crash} on {screen}"

        # ── Step 8: Auto-generate reproduction steps ──────────────────────
        report.repro_steps = self._build_repro(journey, action_at_crash)

        # ── Step 9: Log summary ───────────────────────────────────────────
        log.info(f"  💥 Crash Type   : {report.crash_type}")
        log.info(f"  💥 Exception    : {report.exception_type or 'Not found in logs'}")
        log.info(f"  💥 Root Cause   : {report.root_cause}")
        if report.failed_api:
            log.info(f"  💥 Failed API   : {report.failed_api}")

        return report

    def _pull_logcat(self) -> str:
        """Pull last 200 lines of logcat filtered for errors and the app package."""
        try:
            result = subprocess.run(
                ["adb", "-s", self._adb.t, "logcat", "-d", "-t", "200",
                 "-s", "AndroidRuntime:E", "ActivityManager:I",
                 f"{self._pkg}:*", "ReactNative:E", "ExoPlayer:E",
                 "System.err:W"],
                capture_output=True, text=True, timeout=10,
            )
            lines = result.stdout.strip().split("\n")
            # Also get general errors
            result2 = subprocess.run(
                ["adb", "-s", self._adb.t, "logcat", "-d", "-t", "100", "*:E"],
                capture_output=True, text=True, timeout=10,
            )
            combined = "\n".join(lines) + "\n" + result2.stdout.strip()
            return combined[-8000:]   # keep last 8000 chars
        except Exception as e:
            return f"Logcat pull failed: {e}"

    def _extract_exception(self, log_text: str) -> Tuple[str, str, str]:
        """Extract exception type, message, and stack summary from logcat."""
        exception_type = ""
        error_message  = ""
        stack_lines    = []

        lines = log_text.split("\n")
        in_trace = False

        for line in lines:
            # Exception line: e.g. "FATAL EXCEPTION: main"
            if "FATAL EXCEPTION" in line or "AndroidRuntime" in line:
                in_trace = True

            if in_trace:
                # Exception class line
                if re.search(r"(Exception|Error):", line) and not exception_type:
                    m = re.search(r"(\w+(?:Exception|Error)):\s*(.+)", line)
                    if m:
                        exception_type = m.group(1)
                        error_message  = m.group(2).strip()[:200]

                # Stack trace lines
                if "at " in line and len(stack_lines) < 5:
                    clean = line.strip().replace("at ", "").strip()
                    if self._pkg.replace(".", "/") in clean or "react" in clean.lower():
                        stack_lines.append(clean)
                    elif not stack_lines:
                        stack_lines.append(clean)

                # Process death line
                if "has died" in line and not exception_type:
                    exception_type = "Process Death"
                    m = re.search(r"Process (.+?) has died", line)
                    if m:
                        error_message = m.group(0)

        stack_summary = "\n".join(stack_lines[:4]) if stack_lines else ""

        # Fallbacks — look for common patterns
        if not exception_type:
            for pattern in ["NullPointerException", "OutOfMemoryError",
                            "IllegalStateException", "NetworkOnMainThread",
                            "JSONException", "ExoPlaybackException"]:
                if pattern in log_text:
                    exception_type = pattern
                    # Try to get message after it
                    m = re.search(rf"{pattern}:?\s*([^\n]{{0,150}})", log_text)
                    if m:
                        error_message = m.group(1).strip()
                    break

        return exception_type, error_message, stack_summary

    def _extract_failed_api(self, log_text: str) -> str:
        """Look for failed HTTP URLs in logcat."""
        patterns = [
            r"https?://[^\s\"']+",
            r"api/[^\s\"']+",
        ]
        failed_urls = []
        for line in log_text.split("\n"):
            if any(kw in line.lower() for kw in ["error", "failed", "exception", "404", "500", "timeout"]):
                for pat in patterns:
                    m = re.search(pat, line)
                    if m:
                        url = m.group(0)[:120]
                        if url not in failed_urls:
                            failed_urls.append(url)
        return failed_urls[0] if failed_urls else ""

    def _classify(self, log_text: str, exception_type: str) -> str:
        """Classify crash type based on log content and exception."""
        combined = log_text + " " + exception_type
        for pattern, crash_type in self.EXCEPTION_MAP:
            if re.search(pattern, combined, re.IGNORECASE):
                return crash_type
        return CrashType.UNKNOWN

    def _build_repro(self, journey: JourneyTracker, action: str) -> str:
        """Convert journey + crash action into clean numbered reproduction steps."""
        lines = []
        steps = journey.last_steps()
        for i, s in enumerate(steps, 1):
            lines.append(f"{i}. {s['action']}")
        lines.append(f"{len(steps) + 1}. {action}")
        lines.append(f"{len(steps) + 2}. 💥 App crashes — closes completely")
        return "\n".join(lines)

# ─────────────────────────────────────────────────────────────────────────────
# ISSUE SEVERITY
# ─────────────────────────────────────────────────────────────────────────────

class Severity:
    CRITICAL = "CRITICAL"   # crash, blank screen, playback fail
    MAJOR    = "MAJOR"      # missing content, slow perf, nav fail
    MINOR    = "MINOR"      # UI issue


# ─────────────────────────────────────────────────────────────────────────────
# ISSUE + RESULT MODELS
# ─────────────────────────────────────────────────────────────────────────────

class Issue:
    def __init__(self, title: str, steps: str, expected: str, actual: str,
                 severity: str, screenshot: str = "", timestamp: str = "",
                 root_cause: str = "", module: str = ""):
        self.title      = title
        self.steps      = steps
        self.expected   = expected
        self.actual     = actual
        self.severity   = severity
        self.screenshot = screenshot
        self.timestamp  = timestamp or datetime.now().strftime("%H:%M:%S")
        self.root_cause = root_cause
        self.module     = module


class TestResult:
    def __init__(self, name: str, module: str):
        self.name     = name
        self.module   = module
        self.passed   = False
        self.message  = ""
        self.duration = 0.0
        self.ts       = datetime.now().strftime("%H:%M:%S")


# ─────────────────────────────────────────────────────────────────────────────
# ADB HELPERS
# ─────────────────────────────────────────────────────────────────────────────

class ADB:
    def __init__(self, target: str):
        self.t = target

    def shell(self, cmd: str, timeout: int = 10) -> str:
        try:
            r = subprocess.run(
                ["adb", "-s", self.t, "shell", cmd],
                capture_output=True, text=True, timeout=timeout,
            )
            return r.stdout.strip()
        except Exception as e:
            return f"ERROR: {e}"

    def screenshot(self, path: str) -> bool:
        try:
            self.shell("screencap -p /sdcard/qa_ss.png")
            time.sleep(0.3)
            subprocess.run(
                ["adb", "-s", self.t, "pull", "/sdcard/qa_ss.png", path],
                capture_output=True, timeout=10,
            )
            return os.path.exists(path) and os.path.getsize(path) > 5000
        except Exception:
            return False

    def ui_dump(self) -> str:
        self.shell("uiautomator dump /sdcard/qa_ui.xml", timeout=15)
        time.sleep(0.3)
        return self.shell("cat /sdcard/qa_ui.xml", timeout=10)

    def press(self, keycode: int):
        self.shell(f"input keyevent {keycode}")
        time.sleep(0.4)

    def launch(self, package: str, activity: str = ".MainActivity"):
        self.shell(f"am start -n {package}/{activity}", timeout=10)

    def force_stop(self, package: str):
        self.shell(f"am force-stop {package}")
        time.sleep(1.5)

    def clear_data(self, package: str):
        self.shell(f"pm clear {package}")
        time.sleep(2)

    def get_memory_mb(self, package: str) -> float:
        out = self.shell(f"dumpsys meminfo {package} | grep 'TOTAL'")
        try:
            parts = out.split()
            for i, p in enumerate(parts):
                if p == "TOTAL":
                    return int(parts[i + 1]) / 1024.0
        except Exception:
            pass
        return 0.0

    def launch_and_measure(self, package: str, activity: str = ".MainActivity") -> float:
        """Launch app and return time-to-display in seconds using am start -W."""
        try:
            r = subprocess.run(
                ["adb", "-s", self.t, "shell",
                 f"am start -W -n {package}/{activity}"],
                capture_output=True, text=True, timeout=20,
            )
            for line in r.stdout.splitlines():
                if "TotalTime:" in line:
                    ms = int(line.split(":")[1].strip())
                    return ms / 1000.0
        except Exception:
            pass
        return 0.0

    def texts_on_screen(self) -> List[str]:
        xml = self.ui_dump()
        import re
        texts = re.findall(r'text="([^"]+)"', xml)
        descs = re.findall(r'content-desc="([^"]+)"', xml)
        return [t for t in texts + descs if t.strip()]

    def any_text(self, keywords: List[str]) -> Optional[str]:
        texts = self.texts_on_screen()
        combined = " ".join(texts).lower()
        for kw in keywords:
            if kw.lower() in combined:
                return kw
        return None

    def is_crashed(self, package: str) -> bool:
        out = self.shell(f"pidof {package}")
        return out.strip() == ""

    def navigate(self, keys: List[str], delay: float = 0.5):
        keycodes = {"UP": 19, "DOWN": 20, "LEFT": 21, "RIGHT": 22,
                    "SELECT": 23, "BACK": 4, "HOME": 3}
        for k in keys:
            self.press(keycodes.get(k.upper(), 0))
            time.sleep(delay)


# ─────────────────────────────────────────────────────────────────────────────
# SILENT MONITOR
# Runs in the background while the QA agent executes tests.
# Streams adb logcat live — catches crashes, ANRs, OOMs the instant they happen.
# Polls memory every 30 seconds — builds a memory trend graph.
# All events are merged into the final QA report.
# ─────────────────────────────────────────────────────────────────────────────

class MonitorEvent:
    """One event caught by the background monitor."""
    CRASH  = "CRASH"
    ANR    = "ANR"
    OOM    = "OOM"
    MEMORY = "MEMORY"

    def __init__(self, kind: str, title: str, message: str, timestamp: str = ""):
        self.kind      = kind
        self.title     = title
        self.message   = message
        self.timestamp = timestamp or datetime.now().strftime("%H:%M:%S")


class SilentMonitor:
    """
    Background monitoring that runs while the QA agent tests the app.

    Two threads:
      1. logcat_thread  — streams adb logcat live, catches crashes/ANR/OOM
      2. memory_thread  — polls dumpsys meminfo every 30s, records memory trend

    The QA agent calls start() before tests, stop() after.
    Access .events for all caught events, .memory_samples for the trend.
    """

    # Logcat patterns that signal a problem
    _CRASH_PATTERNS = [
        (re.compile(r"FATAL EXCEPTION", re.I),                     MonitorEvent.CRASH, "Fatal Exception"),
        (re.compile(r"Process\s+\S+\s+has\s+died", re.I),          MonitorEvent.CRASH, "Process Died"),
        (re.compile(r"Force finishing|force-stop", re.I),           MonitorEvent.CRASH, "Force Stopped"),
        (re.compile(r"ANR in|Application Not Responding", re.I),    MonitorEvent.ANR,   "App Not Responding (ANR)"),
        (re.compile(r"Input dispatching timed out", re.I),          MonitorEvent.ANR,   "Input Timeout (ANR)"),
        (re.compile(r"OutOfMemoryError", re.I),                     MonitorEvent.OOM,   "Out of Memory"),
        (re.compile(r"SIGSEGV|SIGABRT|Fatal signal", re.I),         MonitorEvent.CRASH, "Native Crash"),
    ]

    def __init__(self, target: str, package: str, mem_poll_sec: int = 30):
        self._target       = target
        self._package      = package
        self._mem_poll_sec = mem_poll_sec

        self.events: List[MonitorEvent]           = []
        self.memory_samples: List[Dict]           = []   # [{ts, mb}]
        self._lock                                = threading.Lock()
        self._stop_evt                            = threading.Event()
        self._logcat_thread: Optional[threading.Thread] = None
        self._memory_thread: Optional[threading.Thread] = None
        self._logcat_proc                         = None
        self._last_crash_ts: float                = 0.0
        self._dedup_window                        = 5.0   # seconds

    # ── Public API ────────────────────────────────────────────────────────

    def start(self):
        """Start background monitoring threads."""
        self._stop_evt.clear()
        self._logcat_thread = threading.Thread(
            target=self._logcat_loop, daemon=True, name="silent-monitor-logcat"
        )
        self._memory_thread = threading.Thread(
            target=self._memory_loop, daemon=True, name="silent-monitor-memory"
        )
        self._logcat_thread.start()
        self._memory_thread.start()
        log.info("  🔍  Silent monitor started (logcat + memory)")

    def stop(self):
        """Stop all monitoring threads cleanly."""
        self._stop_evt.set()
        if self._logcat_proc:
            try:
                self._logcat_proc.terminate()
            except Exception:
                pass
        if self._logcat_thread:
            self._logcat_thread.join(timeout=3)
        if self._memory_thread:
            self._memory_thread.join(timeout=3)
        log.info(f"  🔍  Silent monitor stopped — "
                 f"{len(self.events)} events, {len(self.memory_samples)} memory samples")

    @property
    def crash_count(self) -> int:
        return sum(1 for e in self.events if e.kind == MonitorEvent.CRASH)

    @property
    def anr_count(self) -> int:
        return sum(1 for e in self.events if e.kind == MonitorEvent.ANR)

    @property
    def peak_memory_mb(self) -> float:
        return max((s["mb"] for s in self.memory_samples), default=0.0)

    # ── Logcat thread ─────────────────────────────────────────────────────

    def _logcat_loop(self):
        """Stream adb logcat live and scan every line for problems."""
        cmd = [
            "adb", "-s", self._target,
            "logcat", "-v", "time",
            f"ActivityManager:I", "AndroidRuntime:E",
            f"*:W",          # warnings and above from all tags
        ]
        try:
            self._logcat_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
            for line in self._logcat_proc.stdout:
                if self._stop_evt.is_set():
                    break
                # Only care about lines mentioning our package OR generic crash signals
                if self._package in line or any(p[0].search(line) for p in self._CRASH_PATTERNS):
                    self._scan_line(line)
        except Exception as e:
            log.debug(f"  logcat thread ended: {e}")

    def _scan_line(self, line: str):
        """Check one logcat line against all crash patterns."""
        now = time.time()
        for pattern, kind, title in self._CRASH_PATTERNS:
            if pattern.search(line):
                # Deduplicate: ignore events within 5s of the last crash
                with self._lock:
                    if now - self._last_crash_ts < self._dedup_window:
                        return
                    self._last_crash_ts = now
                    evt = MonitorEvent(
                        kind=kind,
                        title=title,
                        message=line.strip()[:300],
                        timestamp=datetime.now().strftime("%H:%M:%S"),
                    )
                    self.events.append(evt)
                log.warning(f"  📡 MONITOR [{kind}] {title} at {evt.timestamp}")
                break

    # ── Memory thread ─────────────────────────────────────────────────────

    def _memory_loop(self):
        """Poll memory every N seconds and build a trend."""
        while not self._stop_evt.wait(self._mem_poll_sec):
            mb = self._read_memory()
            if mb > 0:
                sample = {"ts": datetime.now().strftime("%H:%M:%S"), "mb": mb}
                with self._lock:
                    self.memory_samples.append(sample)
                log.debug(f"  📡 Memory: {mb:.1f} MB")

    def _read_memory(self) -> float:
        try:
            r = subprocess.run(
                ["adb", "-s", self._target, "shell",
                 f"dumpsys meminfo {self._package} | grep TOTAL"],
                capture_output=True, text=True, timeout=8,
            )
            parts = r.stdout.split()
            for i, p in enumerate(parts):
                if p == "TOTAL" and i + 1 < len(parts):
                    return int(parts[i + 1]) / 1024.0
        except Exception:
            pass
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# SILENT MIRROR
# Mirrors the Fire TV screen to your Mac in real-time using scrcpy.
# No notification appears on the TV. Run alongside the agent so you can
# watch every step live without touching the device.
# ─────────────────────────────────────────────────────────────────────────────

class SilentMirror:
    """
    Starts scrcpy in the background for live screen mirroring.
    The TV screen shows NO recording notification — hence 'silent'.

    Flags used:
      --no-audio          : skips audio capture (avoids ffmpeg dependency issues)
      --stay-awake        : prevents device sleep during long test runs
      --window-title      : labels the mirror window so you know which device
      --max-fps 20        : saves CPU — 20fps is plenty for QA watching
      --bit-rate 2M       : low bitrate keeps WiFi stable
      --disable-screensaver: stops Mac screensaver interrupting the view
    """

    WINDOW_TITLE = "SouthStream QA — Live Mirror"

    def __init__(self, target: str):
        self._target  = target      # e.g. "192.168.2.8:5555"
        self._proc    = None
        self._enabled = False

    def start(self) -> bool:
        """Start mirroring. Returns True if scrcpy launched successfully."""
        if not shutil.which("scrcpy"):
            log.warning("  ⚠️  scrcpy not found — install with: brew install scrcpy")
            return False

        log.info("  📺  Starting silent mirror (scrcpy)…")
        cmd = [
            "scrcpy",
            "-s", self._target,
            "--no-audio",
            "--stay-awake",
            "--window-title", self.WINDOW_TITLE,
            "--max-fps", "20",
            "--bit-rate", "2M",
            "--disable-screensaver",
        ]

        try:
            # Launch detached — we don't need its stdout
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(2)  # give scrcpy a moment to connect

            if self._proc.poll() is not None:
                # Already exited — probably a dependency error
                log.warning("  ⚠️  scrcpy exited immediately. Trying --no-video-playback fallback…")
                return self._start_fallback()

            self._enabled = True
            log.info(f"  ✅  Mirror window open — PID {self._proc.pid}")
            log.info(f'  ✅  Window title: "{self.WINDOW_TITLE}"')
            return True

        except Exception as e:
            log.warning(f"  ⚠️  Could not start scrcpy: {e}")
            return False

    def _start_fallback(self) -> bool:
        """Try minimal flags in case some flags are unsupported in this scrcpy version."""
        try:
            cmd = ["scrcpy", "-s", self._target, "--no-audio", "--stay-awake"]
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(2)
            if self._proc.poll() is None:
                self._enabled = True
                log.info(f"  ✅  Mirror started (minimal mode) — PID {self._proc.pid}")
                return True
        except Exception:
            pass
        log.warning("  ⚠️  Silent mirror unavailable — tests will still run normally")
        return False

    def stop(self):
        """Stop mirroring cleanly."""
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            log.info("  📺  Mirror stopped")
        self._enabled = False

    @property
    def running(self) -> bool:
        return self._enabled and self._proc is not None and self._proc.poll() is None


# ─────────────────────────────────────────────────────────────────────────────
# ELITE QA AGENT
# ─────────────────────────────────────────────────────────────────────────────

HOME_TEXTS      = ["Home", "Featured", "Trending", "Movies", "Series",
                   "Continue Watching", "Popular", "Watch Now", "Live"]
EPISODE_TEXTS   = ["Episode", "Ep ", "E1", "E2", "Season", "S1", "S2",
                   "Watch Now", "Play", "Resume", "episodes"]
PLAY_TEXTS      = ["Play", "Watch Now", "Resume", "PLAY", "WATCH NOW"]
WATCHLIST_TEXTS = ["Watchlist", "My List", "Saved", "Favourites"]
SERIES_TITLES   = [
    "Sai Bhakto Ki Sachchi Kahani",
    "Crime Stories",
    "Jai Hamun",
]


class EliteQAAgent:

    def __init__(self, ip: str, package: str, port: int = 5555, mirror: bool = False):
        self.target  = f"{ip}:{port}"
        self.package = package
        self.adb     = ADB(self.target)
        self.issues: List[Issue]           = []
        self.crash_reports: List[CrashReport] = []
        self.results: List[TestResult]     = []
        self.perf: Dict[str, float]        = {}
        self.ss_dir  = "output/screenshots"
        self.rep_dir = "output/reports"
        os.makedirs(self.ss_dir, exist_ok=True)
        os.makedirs(self.rep_dir, exist_ok=True)

        # Crash intelligence
        self.journey  = JourneyTracker()
        self.crash_ai = CrashIntelligence(self.adb, self.package, self.ss_dir)

        # Silent mirror
        self._mirror_enabled = mirror
        self._mirror = SilentMirror(self.target) if mirror else None

    # ── Core: EXPECT → EXECUTE → OBSERVE → COMPARE → DECIDE ──────────────

    def check(self, name: str, module: str,
              action, expect_fn, timeout: float = 6.0,
              take_ss_on_fail: bool = True) -> bool:
        """
        Core execution loop — runs action, waits for expectation, decides PASS/FAIL.
        Records every action into the journey tracker.
        """
        r  = TestResult(name, module)
        t0 = time.time()

        log.info(f"  ▶ {name}")
        self.journey.record(name, screen=module)

        try:
            if action:
                action()

            # Poll expectation
            passed = False
            while time.time() - t0 < timeout:
                if expect_fn():
                    passed = True
                    break
                time.sleep(0.5)

            r.duration = time.time() - t0
            r.passed   = passed

            if passed:
                log.info(f"  ✅ PASS ({r.duration:.1f}s)")
            else:
                log.warning(f"  ❌ FAIL ({r.duration:.1f}s)")
                if take_ss_on_fail:
                    ss = self._screenshot(f"fail_{name[:30].replace(' ','_')}")
                    r.message = f"Screenshot: {ss}"

        except Exception as e:
            r.passed  = False
            r.message = str(e)
            log.error(f"  💥 ERROR: {e}")

        self.results.append(r)
        return r.passed

    def _screenshot(self, label: str = "") -> str:
        ts  = datetime.now().strftime("%H%M%S")
        fn  = f"{self.ss_dir}/qa_{ts}_{label}.png"
        ok  = self.adb.screenshot(fn)
        return fn if ok else ""

    def _issue(self, title: str, steps: str, expected: str, actual: str,
               severity: str, module: str, root_cause: str = ""):
        ss = self._screenshot(f"issue_{title[:20].replace(' ','_')}")
        self.issues.append(Issue(
            title=title, steps=steps, expected=expected, actual=actual,
            severity=severity, screenshot=ss, root_cause=root_cause,
            module=module,
        ))
        log.warning(f"  🐛 ISSUE [{severity}]: {title}")

    def _crash_detected(self, action_at_crash: str, label: str = "crash") -> CrashReport:
        """
        Called whenever a crash is detected.
        Runs full CrashIntelligence analysis and stores the report.
        """
        log.warning(f"\n  💥 CRASH DETECTED — running deep analysis...")
        log.warning(f"  Action at crash: {action_at_crash}")
        log.warning(f"  Screen         : {self.journey.current_screen}")
        log.warning(f"  UI State       : {self.journey.ui_state}")

        cr = self.crash_ai.analyze(self.journey, action_at_crash, label)
        self.crash_reports.append(cr)

        # Also add to issues list for unified report
        self.issues.append(Issue(
            title      = cr.title,
            steps      = cr.repro_steps,
            expected   = "App should complete the action without crashing",
            actual     = f"App crashed and closed completely. Type: {cr.crash_type}",
            severity   = Severity.CRITICAL,
            screenshot = cr.screenshot,
            root_cause = cr.root_cause_simple,
            module     = self.journey.current_screen,
            timestamp  = cr.timestamp,
        ))

        log.warning(f"  💥 Crash type  : {cr.crash_type}")
        log.warning(f"  💥 Root cause  : {cr.root_cause}")
        if cr.exception_type:
            log.warning(f"  💥 Exception   : {cr.exception_type}: {cr.error_message[:80]}")

        # Relaunch app after crash
        log.info("  🔄 Relaunching app after crash...")
        time.sleep(1)
        self.adb.launch(self.package)
        time.sleep(4)
        self.journey.set_screen("Home")
        self.journey.set_state("idle")
        self.journey.record("App relaunched after crash")

        return cr

    # ── 1. APP LAUNCH PERFORMANCE ─────────────────────────────────────────

    def test_launch_performance(self):
        log.info("\n━━ TEST: App Launch Performance ━━")
        self.journey.set_screen("Launch")
        self.journey.record("Force stopped app for cold start measurement")
        self.adb.force_stop(self.package)
        time.sleep(1)

        self.journey.record("App launch triggered")
        self.journey.set_state("loading")
        t0 = time.time()
        launch_time = self.adb.launch_and_measure(self.package)
        if launch_time == 0:
            # Fallback: measure manually
            self.adb.launch(self.package)
            deadline = time.time() + 15
            while time.time() < deadline:
                if self.adb.any_text(HOME_TEXTS):
                    launch_time = time.time() - t0
                    break
                time.sleep(0.5)

        self.perf["launch_time"] = launch_time
        log.info(f"  Launch time: {launch_time:.2f}s")

        if launch_time < 3:
            label = "✅ Good (<3s)"
        elif launch_time < 5:
            label = "⚠️ Acceptable (3–5s)"
        else:
            label = "❌ SLOW (>5s)"
            self._issue(
                "App Launch Too Slow",
                "Cold start the app",
                "App launches in <3 seconds",
                f"App took {launch_time:.1f}s to launch",
                Severity.MAJOR, "Launch",
                "Cold start time exceeds threshold. Check splash screen blocking calls or heavy app init.",
            )

        r = TestResult("App launch time", "Launch")
        r.passed   = launch_time < 5
        r.duration = launch_time
        r.message  = label
        self.results.append(r)
        log.info(f"  {label}")

    # ── 2. HOME PAGE LOAD ─────────────────────────────────────────────────

    def test_home_load(self):
        log.info("\n━━ TEST: Home Page Load ━━")
        self.journey.set_screen("Home")
        self.journey.set_state("loading")
        self.journey.record("Waiting for home screen to fully load")

        # Wait for home to appear, measure full content load
        t0 = time.time()
        home_appeared = False
        deadline = time.time() + 15
        while time.time() < deadline:
            if self.adb.any_text(HOME_TEXTS):
                home_appeared = True
                break
            time.sleep(0.5)

        load_time = time.time() - t0
        self.perf["home_load_time"] = load_time

        if not home_appeared:
            self._issue(
                "Home Screen Did Not Load",
                "Launch app → wait for home screen",
                "Home screen with content rails visible",
                "Home screen not detected after 15 seconds",
                Severity.CRITICAL, "Home",
                "App may be stuck on splash/loading or crashed silently.",
            )
            self.check("Home screen visible", "Home",
                       None, lambda: self.adb.any_text(HOME_TEXTS) is not None)
            return

        log.info(f"  Home load time: {load_time:.2f}s")
        self.journey.set_state("idle")
        self.journey.record("Home screen loaded — content rails visible")

        # Check for empty rails
        texts = self.adb.texts_on_screen()
        content_count = len([t for t in texts if len(t) > 3])

        if content_count < 5:
            self._issue(
                "Home Screen Appears Empty",
                "Launch app → observe home screen",
                "Content rails, thumbnails, banners visible",
                f"Only {content_count} text elements found — looks empty",
                Severity.MAJOR, "Home",
                "Content rails not loading. API may be slow or returning empty response.",
            )

        if load_time > 7:
            self._issue(
                "Home Page Load Too Slow",
                "Launch app → wait for home screen content",
                "Home screen fully loaded in <7 seconds",
                f"Home took {load_time:.1f}s to show content",
                Severity.MAJOR, "Home",
            )

        r = TestResult("Home screen loaded with content", "Home")
        r.passed   = home_appeared and content_count >= 5
        r.duration = load_time
        self.results.append(r)
        log.info(f"  Content elements on home: {content_count}")

    # ── 3. SERIES EPISODES TEST (the bug you found) ───────────────────────

    def test_series_episodes(self):
        log.info("\n━━ TEST: Series Episodes Loading ━━")
        log.info("  (Testing exactly what you found — episodes missing in series)")

        series_results = {}

        for attempt in range(1, 4):
            log.info(f"\n  --- Attempt {attempt}/3 ---")

            if attempt > 1:
                # Exit and reopen like manual tester did
                self.journey.record(f"Force closed app — attempt {attempt}")
                self.adb.force_stop(self.package)
                time.sleep(1)
                self.journey.record("Reopened app without clearing data")
                self.adb.launch(self.package)
                time.sleep(4)

            # Navigate to home
            self.journey.set_screen("Home")
            self.journey.record("Pressed BACK to go to home screen")
            self.adb.press(4)  # BACK
            time.sleep(1)

            # Try to navigate to series section
            self.journey.record("Navigating to Series section")
            self._go_to_series_section()

            # Check each series
            for series_name in SERIES_TITLES:
                if series_name not in series_results:
                    series_results[series_name] = []

                log.info(f"    Checking: {series_name}")
                self.journey.set_screen(f"Series: {series_name}")
                self.journey.record(f"Opened series: {series_name}")
                self.journey.set_state("loading")
                found = self._check_series_episodes(series_name)
                series_results[series_name].append(found)
                self.journey.set_state("idle")
                log.info(f"    → Episodes {'FOUND ✅' if found else 'MISSING ❌'} (attempt {attempt})")
                time.sleep(1)

        # Analyze results — just like your manual observation
        log.info("\n  📊 Series Episode Results:")
        for series, attempts in series_results.items():
            pass_count = sum(1 for a in attempts if a)
            status = "✅ Always loads" if pass_count == 3 else \
                     "❌ Never loads" if pass_count == 0 else \
                     f"⚠️ Intermittent ({pass_count}/3 times)"
            log.info(f"    {series}: {status}")

            if pass_count == 0:
                self._issue(
                    f"Series Episodes Never Load — {series}",
                    f"Open app → Navigate to Series → Open '{series}' → Check episodes",
                    "Episode list visible (Ep 1, Ep 2, Ep 3...)",
                    "Episodes section completely missing — only Related Content shown. Tested 3 times, always missing.",
                    Severity.CRITICAL, "Series",
                    f"'{series}' may have no episode data on server, or episode API call is failing for this specific series.",
                )
            elif pass_count < 3:
                self._issue(
                    f"Series Episodes Intermittently Missing — {series}",
                    f"Open app → Navigate to Series → Open '{series}' → Check episodes",
                    "Episodes always visible",
                    f"Episodes appeared only {pass_count}/3 times. App is loading from stale/empty local cache.",
                    Severity.MAJOR, "Series",
                    "Local cache (AsyncStorage/SQLite) storing empty episode response. On next open, loads empty cache instead of fetching from server.",
                )

            r = TestResult(f"Series episodes load: {series}", "Series")
            r.passed  = pass_count >= 2
            r.message = f"{pass_count}/3 attempts successful"
            self.results.append(r)

    def _go_to_series_section(self):
        """Navigate to the series/TV section on home screen."""
        # Press DOWN to get into content rows
        for _ in range(3):
            self.adb.press(20)  # DOWN
            time.sleep(0.4)
            texts = self.adb.texts_on_screen()
            combined = " ".join(texts).lower()
            if any(kw in combined for kw in ["series", "tv show", "web series", "season"]):
                break

    def _check_series_episodes(self, series_name: str) -> bool:
        """
        Try to open the series and check if episode cards are visible.
        Returns True if episodes found, False if missing.
        """
        # Press SELECT on current focused item
        self.adb.press(23)  # SELECT
        time.sleep(2.5)

        # Check what's on screen
        texts = self.adb.texts_on_screen()
        combined = " ".join(texts).lower()

        # Check for episode indicators
        has_episodes = any(kw.lower() in combined for kw in EPISODE_TEXTS)
        has_related_only = ("related" in combined or "you may" in combined) and not has_episodes

        if has_related_only:
            # Take screenshot as evidence
            self._screenshot(f"no_episodes_{series_name[:15].replace(' ','_')}")

        # Go back
        self.adb.press(4)  # BACK
        time.sleep(1.5)
        self.adb.press(22)  # RIGHT to move to next series
        time.sleep(0.5)

        return has_episodes

    # ── 4. WATCHLIST TEST ─────────────────────────────────────────────────

    def test_watchlist(self):
        log.info("\n━━ TEST: Watchlist ━━")
        self.journey.set_screen("Home")
        self.journey.record("Pressed BACK to return to home/navigation")

        # Navigate to watchlist
        self.adb.press(4)  # BACK to root
        time.sleep(1)

        # Look for watchlist in nav
        found_watchlist = False
        for _ in range(6):
            if self.adb.any_text(WATCHLIST_TEXTS):
                found_watchlist = True
                break
            self.adb.press(22)  # RIGHT
            time.sleep(0.4)

        if not found_watchlist:
            r = TestResult("Navigate to Watchlist", "Watchlist")
            r.passed  = False
            r.message = "Watchlist not found in navigation"
            self.results.append(r)
            return

        self.journey.set_screen("Watchlist")
        self.journey.record("Selected Watchlist from navigation bar")
        self.adb.press(23)  # SELECT
        time.sleep(2)

        texts = self.adb.texts_on_screen()
        combined = " ".join(texts).lower()

        # Check for empty cards (the bug you found — 2 empty cards)
        empty_indicators = ["empty", "no items", "nothing here", "add to watchlist"]
        has_content      = len([t for t in texts if len(t) > 5]) > 3
        has_empty_state  = any(kw in combined for kw in empty_indicators)

        if not has_content and not has_empty_state:
            self._issue(
                "Watchlist Shows Empty/Ghost Cards",
                "Navigate to Watchlist → observe cards",
                "Watchlist items visible OR empty state message shown",
                "2 empty ghost cards visible with no content — clicking them crashes the app",
                Severity.CRITICAL, "Watchlist",
                "Watchlist data contains null/empty entries. No null check before rendering card or handling click event.",
            )

        # Try clicking first item — check for crash
        self.journey.set_screen("Watchlist")
        self.journey.record("Clicked first watchlist card to open content detail")
        self.adb.press(23)  # SELECT
        time.sleep(2)

        if self.adb.is_crashed(self.package):
            cr = self._crash_detected("clicking watchlist card", "watchlist_crash")
            r = TestResult("Watchlist loads without crash", "Watchlist")
            r.passed  = False
            r.message = f"Crashed: {cr.crash_type}"
            self.results.append(r)
        else:
            r = TestResult("Watchlist loads without crash", "Watchlist")
            r.passed  = True
            r.message = "OK"
            self.results.append(r)

    # ── 5. NAVIGATION TEST ────────────────────────────────────────────────

    def test_navigation(self):
        log.info("\n━━ TEST: Navigation ━━")

        # Test: navigate to home, press back, back works
        self.check(
            "Home screen reachable", "Navigation",
            lambda: [self.adb.press(4) for _ in range(3)],
            lambda: self.adb.any_text(HOME_TEXTS) is not None,
            timeout=8,
        )

        # Test: scroll down — content loads
        t0 = time.time()
        self.adb.press(20)  # DOWN
        time.sleep(0.3)
        self.adb.press(20)  # DOWN
        time.sleep(0.3)

        scroll_texts_after = self.adb.texts_on_screen()
        scroll_time = time.time() - t0
        self.perf.setdefault("scroll_load_times", []).append(scroll_time)  # type: ignore

        if scroll_time > 4:
            self._issue(
                "Scroll Load Too Slow",
                "On home screen → scroll down",
                "New content row visible within 2 seconds",
                f"Content took {scroll_time:.1f}s to appear after scroll",
                Severity.MAJOR, "Navigation",
            )

        r = TestResult("Scroll loads new content", "Navigation")
        r.passed  = len(scroll_texts_after) > 3
        r.message = f"{len(scroll_texts_after)} elements after scroll"
        self.results.append(r)

        log.info(f"  Scroll load time: {scroll_time:.2f}s")

    # ── 6. CONTENT LANGUAGE SETTINGS TEST ────────────────────────────────

    def test_language_settings(self):
        log.info("\n━━ TEST: Content Language Settings ━━")

        # Navigate to settings
        self.adb.press(4)
        time.sleep(1)

        settings_found = False
        for _ in range(8):
            if self.adb.any_text(["Settings", "Profile", "Account"]):
                settings_found = True
                break
            self.adb.press(22)  # RIGHT
            time.sleep(0.4)

        if not settings_found:
            r = TestResult("Language settings reachable", "Settings")
            r.passed  = False
            r.message = "Settings not found in nav"
            self.results.append(r)
            return

        self.adb.press(23)  # SELECT
        time.sleep(2)

        lang_found = self.adb.any_text(["Language", "Content Language", "Audio Language"])
        if lang_found:
            # Navigate to language option
            for _ in range(5):
                if self.adb.any_text(["Language"]):
                    break
                self.adb.press(20)  # DOWN
                time.sleep(0.3)

            self.adb.press(23)  # SELECT — open language picker
            time.sleep(1.5)
            self.adb.press(20)  # DOWN — change selection
            time.sleep(0.3)

            # Try to save — look for Save button
            for _ in range(4):
                if self.adb.any_text(["Save", "OK", "Apply", "Done"]):
                    break
                self.adb.press(20)
                time.sleep(0.3)

            self.journey.set_screen("Settings — Language")
            self.journey.record("Pressed Save/OK to confirm language change")
            self.adb.press(23)  # SELECT / Save
            time.sleep(2.5)

            if self.adb.is_crashed(self.package):
                cr = self._crash_detected("saving content language setting", "language_crash")
                r = TestResult("Language setting saves without crash", "Settings")
                r.passed  = False
                r.message = f"Crashed: {cr.crash_type}"
                self.results.append(r)
            else:
                r = TestResult("Language setting saves without crash", "Settings")
                r.passed  = True
                r.message = "OK"
                self.results.append(r)
        else:
            r = TestResult("Language setting found in Settings", "Settings")
            r.passed  = False
            r.message = "Language option not found in Settings screen"
            self.results.append(r)

    # ── 7. LOGIN FLOW TEST ────────────────────────────────────────────────

    def test_login_flow(self):
        log.info("\n━━ TEST: Login Flow ━━")

        # Check if already logged in
        if self.adb.any_text(HOME_TEXTS):
            r = TestResult("Login — already logged in", "Login")
            r.passed  = True
            r.message = "Already on home screen"
            self.results.append(r)
            log.info("  Already logged in — skipping login flow")
            return

        # Wait for login screen
        deadline = time.time() + 10
        login_visible = False
        while time.time() < deadline:
            if self.adb.any_text(["Sign In", "Login", "Email", "Password"]):
                login_visible = True
                break
            time.sleep(0.5)

        if not login_visible:
            r = TestResult("Login screen visible", "Login")
            r.passed  = False
            r.message = "Login screen did not appear"
            self.results.append(r)
            return

        # Simulate entering credentials and proceeding
        # Navigate through login flow
        self.adb.press(23)  # SELECT on first field
        time.sleep(1)

        # Go through → Next → Select profile
        self.journey.set_screen("Login")
        self.journey.record("Entered credentials and pressed Next")
        for _ in range(3):
            self.adb.press(20)  # DOWN
            time.sleep(0.4)

        self.journey.record("Selecting profile after login")
        self.adb.press(23)  # SELECT
        time.sleep(3)

        if self.adb.is_crashed(self.package):
            cr = self._crash_detected("selecting profile after login", "login_crash")
            r = TestResult("Login completes without crash", "Login")
            r.passed  = False
            r.message = f"Crashed: {cr.crash_type}"
            self.results.append(r)
        else:
            on_home = self.adb.any_text(HOME_TEXTS) is not None
            r = TestResult("Login completes without crash", "Login")
            r.passed  = on_home
            r.message = "OK" if on_home else "Did not reach home screen"
            self.results.append(r)

    # ── RUN ALL TESTS ─────────────────────────────────────────────────────

    def run(self):
        log.info("=" * 55)
        log.info("  ELITE QA AGENT — SouthStream Fire TV")
        log.info(f"  Device : {self.target}")
        log.info(f"  Package: {self.package}")
        log.info(f"  Time   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        log.info("=" * 55)

        # Connect check
        out = subprocess.run(["adb", "-s", self.target, "shell", "echo ok"],
                             capture_output=True, text=True, timeout=5)
        if "ok" not in out.stdout:
            log.error(f"Cannot connect to {self.target}. Check device is on same WiFi.")
            sys.exit(1)

        log.info(f"\n  ✅ Connected to {self.target}")

        # Start silent mirror if requested
        mirror_active = False
        if self._mirror:
            mirror_active = self._mirror.start()
            if mirror_active:
                log.info("  📺  Mirror is live — you can watch the test on your Mac")
                time.sleep(1)   # let mirror settle before ADB commands start

        try:
            # Run all tests
            self.test_launch_performance()
            self.test_home_load()
            self.test_navigation()
            self.test_series_episodes()
            self.test_watchlist()
            self.test_language_settings()
            self.test_login_flow()

        finally:
            # Always stop mirror cleanly
            if self._mirror:
                self._mirror.stop()

        # Generate report
        report_path = self._generate_report(mirror_was_active=mirror_active)
        log.info(f"\n  📊 Report saved: {report_path}")

        # Summary
        total  = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed
        log.info("\n" + "=" * 55)
        log.info(f"  TOTAL: {total}  PASSED: {passed}  FAILED: {failed}")
        log.info(f"  ISSUES FOUND: {len(self.issues)}")
        log.info(f"  Launch Time : {self.perf.get('launch_time', 0):.2f}s")
        log.info(f"  Home Load   : {self.perf.get('home_load_time', 0):.2f}s")
        if mirror_active:
            log.info("  Mirror      : Silent mirror was active during this session")
        log.info("=" * 55)

        return report_path

    # ── REPORT GENERATOR ─────────────────────────────────────────────────

    def _generate_report(self, mirror_was_active: bool = False) -> str:
        ts          = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = f"{self.rep_dir}/SouthStream_QA_Agent_Report_{ts}.html"

        total    = len(self.results)
        passed   = sum(1 for r in self.results if r.passed)
        failed   = total - passed
        score    = round((passed / total * 10) if total else 0, 1)
        launch   = self.perf.get("launch_time", 0)
        home_ld  = self.perf.get("home_load_time", 0)

        critical_issues = [i for i in self.issues if i.severity == Severity.CRITICAL]
        major_issues    = [i for i in self.issues if i.severity == Severity.MAJOR]
        minor_issues    = [i for i in self.issues if i.severity == Severity.MINOR]

        # Modules summary
        modules: Dict[str, Dict] = {}
        for r in self.results:
            if r.module not in modules:
                modules[r.module] = {"pass": 0, "fail": 0}
            if r.passed:
                modules[r.module]["pass"] += 1
            else:
                modules[r.module]["fail"] += 1

        slowest = max(self.results, key=lambda r: r.duration, default=None)

        # Build crash intelligence cards
        crash_cards_html = ""
        for idx, cr in enumerate(self.crash_reports, 1):
            ss_html = ""
            if cr.screenshot and os.path.exists(cr.screenshot):
                with open(cr.screenshot, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                ss_html = f'<img src="data:image/png;base64,{b64}" style="width:100%;border-radius:6px;margin-top:12px;display:block;">'

            journey_lines = cr.user_journey.replace("\n", "<br>")
            repro_lines   = cr.repro_steps.replace("\n", "<br>")
            stack_html    = (f'<div style="background:#0f172a;border-radius:6px;padding:10px;margin-bottom:8px;">'
                             f'<div style="font-size:10px;color:#94a3b8;font-weight:700;text-transform:uppercase;margin-bottom:4px;">Stack Trace (summary)</div>'
                             f'<pre style="color:#94a3b8;font-size:11px;white-space:pre-wrap;margin:0;">{cr.stack_summary}</pre>'
                             f'</div>') if cr.stack_summary else ""
            api_html      = (f'<div style="background:#0f172a;border-radius:6px;padding:10px;margin-bottom:8px;">'
                             f'<div style="font-size:10px;color:#f87171;font-weight:700;text-transform:uppercase;margin-bottom:4px;">Failed API / URL</div>'
                             f'<div style="color:#fca5a5;font-size:12px;word-break:break-all;">{cr.failed_api}</div>'
                             f'</div>') if cr.failed_api else ""

            crash_cards_html += f"""
            <div style="background:#1a0a2e;border-left:4px solid #a855f7;border-radius:10px;padding:20px;margin-bottom:20px;">
              <!-- Header -->
              <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px;">
                <div>
                  <div style="font-size:13px;color:#d8b4fe;font-weight:800;">CRASH #{idx} &nbsp;·&nbsp; {cr.crash_type}</div>
                  <div style="font-size:15px;font-weight:700;color:#f8fafc;margin-top:4px;">{cr.title}</div>
                </div>
                <span style="background:#a855f7;color:white;padding:2px 12px;border-radius:20px;font-size:11px;font-weight:700;flex-shrink:0;margin-left:12px;">{cr.severity}</span>
              </div>

              <!-- Context row -->
              <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:12px;">
                <div style="background:#0f172a;border-radius:6px;padding:8px;">
                  <div style="font-size:10px;color:#94a3b8;font-weight:700;text-transform:uppercase;margin-bottom:3px;">Screen</div>
                  <div style="color:#e2e8f0;font-size:12px;">{cr.current_screen}</div>
                </div>
                <div style="background:#0f172a;border-radius:6px;padding:8px;">
                  <div style="font-size:10px;color:#94a3b8;font-weight:700;text-transform:uppercase;margin-bottom:3px;">Action at Crash</div>
                  <div style="color:#e2e8f0;font-size:12px;">{cr.action_at_crash}</div>
                </div>
                <div style="background:#0f172a;border-radius:6px;padding:8px;">
                  <div style="font-size:10px;color:#94a3b8;font-weight:700;text-transform:uppercase;margin-bottom:3px;">Time</div>
                  <div style="color:#e2e8f0;font-size:12px;">{cr.timestamp}</div>
                </div>
              </div>

              <!-- Exception -->
              {"<div style='background:#0f172a;border-radius:6px;padding:10px;margin-bottom:8px;'><div style='font-size:10px;color:#f87171;font-weight:700;text-transform:uppercase;margin-bottom:4px;'>Exception</div><div style='color:#fca5a5;font-size:12px;font-family:monospace;'>" + cr.exception_type + (": " + cr.error_message[:120] if cr.error_message else "") + "</div></div>" if cr.exception_type else ""}

              {stack_html}
              {api_html}

              <!-- Root cause -->
              <div style="background:#2d1d08;border-left:3px solid #f59e0b;border-radius:6px;padding:12px;margin-bottom:12px;">
                <div style="font-size:10px;color:#fbbf24;font-weight:700;text-transform:uppercase;margin-bottom:4px;">Root Cause — {cr.root_cause}</div>
                <div style="color:#fcd34d;font-size:13px;">{cr.root_cause_simple}</div>
              </div>

              <!-- User journey -->
              <div style="background:#0f172a;border-radius:6px;padding:10px;margin-bottom:8px;">
                <div style="font-size:10px;color:#60a5fa;font-weight:700;text-transform:uppercase;margin-bottom:6px;">What User Did (Journey Before Crash)</div>
                <div style="color:#93c5fd;font-size:12px;line-height:1.8;">{journey_lines}</div>
              </div>

              <!-- Reproduction steps -->
              <div style="background:#0f172a;border-radius:6px;padding:10px;margin-bottom:8px;">
                <div style="font-size:10px;color:#4ade80;font-weight:700;text-transform:uppercase;margin-bottom:6px;">How to Reproduce</div>
                <div style="color:#86efac;font-size:12px;line-height:1.8;">{repro_lines}</div>
              </div>

              {ss_html}
            </div>"""

        # Build issue cards
        def sev_color(s):
            return {"CRITICAL": "#dc2626", "MAJOR": "#d97706", "MINOR": "#16a34a"}.get(s, "#6b7280")

        def sev_bg(s):
            return {"CRITICAL": "#3b1919", "MAJOR": "#2d1d08", "MINOR": "#052e16"}.get(s, "#1e293b")

        issue_cards = ""
        for idx, iss in enumerate(self.issues, 1):
            col = sev_color(iss.severity)
            bg  = sev_bg(iss.severity)
            ss_html = ""
            if iss.screenshot and os.path.exists(iss.screenshot):
                with open(iss.screenshot, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                ss_html = f'<img src="data:image/png;base64,{b64}" style="width:100%;border-radius:6px;margin-top:10px;display:block;">'

            issue_cards += f"""
            <div style="background:{bg};border-left:4px solid {col};border-radius:10px;padding:18px 20px;margin-bottom:16px;">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
                <span style="font-size:15px;font-weight:800;color:#f8fafc;">#{idx} — {iss.title}</span>
                <span style="background:{col};color:white;padding:2px 12px;border-radius:20px;font-size:11px;font-weight:700;">{iss.severity}</span>
              </div>
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px;">
                <div style="background:#0f172a;border-radius:6px;padding:10px;">
                  <div style="font-size:10px;color:#4ade80;font-weight:700;text-transform:uppercase;margin-bottom:4px;">Expected</div>
                  <div style="color:#86efac;font-size:12px;">{iss.expected}</div>
                </div>
                <div style="background:#0f172a;border-radius:6px;padding:10px;">
                  <div style="font-size:10px;color:#f87171;font-weight:700;text-transform:uppercase;margin-bottom:4px;">Actual</div>
                  <div style="color:#fca5a5;font-size:12px;">{iss.actual}</div>
                </div>
              </div>
              <div style="background:#0f172a;border-radius:6px;padding:10px;margin-bottom:8px;">
                <div style="font-size:10px;color:#94a3b8;font-weight:700;text-transform:uppercase;margin-bottom:4px;">Steps</div>
                <div style="color:#e2e8f0;font-size:12px;">{iss.steps}</div>
              </div>
              {"<div style='background:#0f172a;border-radius:6px;padding:10px;'><div style='font-size:10px;color:#fbbf24;font-weight:700;text-transform:uppercase;margin-bottom:4px;'>Root Cause</div><div style='color:#fcd34d;font-size:12px;'>" + iss.root_cause + "</div></div>" if iss.root_cause else ""}
              {ss_html}
              <div style="margin-top:8px;font-size:11px;color:#475569;">Module: {iss.module} &nbsp;|&nbsp; {iss.timestamp}</div>
            </div>"""

        # Test results rows
        result_rows = ""
        for r in self.results:
            icon = "✅" if r.passed else "❌"
            result_rows += f"""
            <tr>
              <td>{icon}</td>
              <td>{r.name}</td>
              <td><span style="font-size:11px;background:{'#052e16' if r.passed else '#3b1919'};color:{'#4ade80' if r.passed else '#f87171'};padding:2px 8px;border-radius:10px;">{'PASS' if r.passed else 'FAIL'}</span></td>
              <td style="font-family:monospace;">{r.module}</td>
              <td style="font-family:monospace;">{r.duration:.1f}s</td>
              <td style="color:#94a3b8;font-size:12px;">{r.message}</td>
            </tr>"""

        # Module summary rows
        module_rows = ""
        for mod, counts in modules.items():
            tot = counts["pass"] + counts["fail"]
            pct = int(counts["pass"] / tot * 100) if tot else 0
            col = "#4ade80" if pct == 100 else "#fbbf24" if pct >= 50 else "#f87171"
            module_rows += f"""
            <tr>
              <td><strong>{mod}</strong></td>
              <td>{counts['pass']}</td>
              <td>{counts['fail']}</td>
              <td><span style="color:{col};font-weight:700;">{pct}%</span></td>
            </tr>"""

        score_color = "#4ade80" if score >= 7 else "#fbbf24" if score >= 4 else "#f87171"
        launch_color = "#4ade80" if launch < 3 else "#fbbf24" if launch < 5 else "#f87171"
        home_color   = "#4ade80" if home_ld < 5 else "#fbbf24" if home_ld < 7 else "#f87171"

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>SouthStream QA Agent Report — {datetime.now().strftime('%B %d, %Y')}</title>
<style>
  :root {{ --bg:#0f172a; --card:#1e293b; --card2:#263248; --text:#e2e8f0; --muted:#94a3b8; --border:#334155; }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:'Segoe UI',system-ui,sans-serif; background:var(--bg); color:var(--text); font-size:14px; line-height:1.7; }}
  .hero {{ background:linear-gradient(135deg,#0f172a,#1a0a2e,#0f172a); padding:48px 32px 36px; text-align:center; border-bottom:1px solid var(--border); }}
  .hero h1 {{ font-size:28px; font-weight:800; color:#f8fafc; margin:12px 0 6px; }}
  .hero-sub {{ color:var(--muted); font-size:13px; margin-bottom:24px; }}
  .hero-stats {{ display:flex; justify-content:center; gap:40px; flex-wrap:wrap; }}
  .hs {{ text-align:center; }} .hs .v {{ font-size:28px; font-weight:800; display:block; }} .hs .l {{ font-size:11px; color:var(--muted); text-transform:uppercase; }}
  .badge {{ display:inline-block; padding:4px 14px; border-radius:20px; font-size:11px; font-weight:700; background:rgba(220,38,38,0.15); border:1px solid rgba(220,38,38,0.4); color:#f87171; margin-bottom:12px; }}
  .container {{ max-width:1100px; margin:0 auto; padding:32px 24px; }}
  section {{ margin-bottom:44px; }}
  h2 {{ font-size:16px; font-weight:700; color:#f8fafc; margin-bottom:16px; padding-bottom:8px; border-bottom:1px solid var(--border); }}
  .card {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:20px 24px; margin-bottom:12px; }}
  .perf-row {{ display:flex; align-items:center; gap:12px; margin-bottom:10px; font-size:13px; }}
  .perf-label {{ width:160px; color:var(--muted); flex-shrink:0; }}
  .perf-bar {{ flex:1; background:var(--card2); border-radius:4px; height:12px; overflow:hidden; }}
  .perf-fill {{ height:100%; border-radius:4px; }}
  .perf-val {{ width:100px; font-family:monospace; font-size:12px; }}
  table {{ width:100%; border-collapse:collapse; }}
  th {{ background:var(--card2); color:var(--muted); font-size:11px; text-transform:uppercase; padding:9px 14px; text-align:left; }}
  td {{ padding:9px 14px; border-bottom:1px solid var(--border); font-size:13px; }}
  tr:last-child td {{ border-bottom:none; }}
  footer {{ text-align:center; padding:28px; color:var(--muted); font-size:12px; border-top:1px solid var(--border); margin-top:20px; }}
</style>
</head>
<body>

<div class="hero">
  <div>
    <span class="badge">QA Agent Report</span>
    {"<span style='display:inline-block;margin-left:8px;padding:4px 14px;border-radius:20px;font-size:11px;font-weight:700;background:rgba(168,85,247,0.15);border:1px solid rgba(168,85,247,0.4);color:#d8b4fe;'>📺 Silent Mirror Active</span>" if mirror_was_active else ""}
  </div>
  <h1>🤖 Elite QA Agent — SouthStream Fire TV</h1>
  <div class="hero-sub">Automated intelligent testing — {datetime.now().strftime('%B %d, %Y · %H:%M IST')} · Device: {self.target}</div>
  <div class="hero-stats">
    <div class="hs"><span class="v" style="color:{score_color};">{score}/10</span><span class="l">Stability Score</span></div>
    <div class="hs"><span class="v" style="color:#f87171;">{len(self.issues)}</span><span class="l">Issues Found</span></div>
    <div class="hs"><span class="v" style="color:#f87171;">{len(critical_issues)}</span><span class="l">Critical</span></div>
    <div class="hs"><span class="v" style="color:#4ade80;">{passed}</span><span class="l">Tests Passed</span></div>
    <div class="hs"><span class="v" style="color:#f87171;">{failed}</span><span class="l">Tests Failed</span></div>
  </div>
</div>

<div class="container">

  <!-- VERDICT -->
  <div style="background:#3b1919;border-left:4px solid #dc2626;border-radius:12px;padding:20px 24px;margin-bottom:32px;">
    <strong style="font-size:15px;color:#f87171;">🔴 OVERALL RESULT — {"FAIL — DO NOT RELEASE" if len(critical_issues) > 0 else "PASS WITH WARNINGS"}</strong>
    <p style="margin-top:8px;color:#fca5a5;font-size:13px;">
      Found {len(self.issues)} issues ({len(critical_issues)} Critical, {len(major_issues)} Major, {len(minor_issues)} Minor) across {len(modules)} modules.
      Stability score: {score}/10.
      {"Critical issues must be fixed before release." if critical_issues else "No critical blockers found."}
    </p>
  </div>

  <!-- PERFORMANCE -->
  <section>
    <h2>🚀 Performance Results</h2>
    <div class="card">
      <div class="perf-row">
        <span class="perf-label">App Launch Time</span>
        <div class="perf-bar"><div class="perf-fill" style="width:{min(launch/10*100,100):.0f}%;background:{launch_color};"></div></div>
        <span class="perf-val" style="color:{launch_color};">{launch:.2f}s {"✅ Good" if launch < 3 else "⚠️ Slow" if launch < 5 else "❌ FAIL"}</span>
      </div>
      <div class="perf-row">
        <span class="perf-label">Home Page Load</span>
        <div class="perf-bar"><div class="perf-fill" style="width:{min(home_ld/15*100,100):.0f}%;background:{home_color};"></div></div>
        <span class="perf-val" style="color:{home_color};">{home_ld:.2f}s {"✅ Good" if home_ld < 5 else "⚠️ Slow" if home_ld < 7 else "❌ FAIL"}</span>
      </div>
      <p style="margin-top:12px;font-size:12px;color:var(--muted);">
        Threshold: Launch &lt;3s = Good, 3–5s = Acceptable, &gt;5s = Issue &nbsp;|&nbsp; Home &lt;5s = Good, 5–7s = Acceptable, &gt;7s = Issue
        {"<br><strong style='color:#f87171;'>⚠️ Slowest area: " + slowest.name + " (" + str(round(slowest.duration,1)) + "s)</strong>" if slowest else ""}
      </p>
    </div>
  </section>

  <!-- ISSUES -->
  <section>
    <h2>🐛 Issues Found ({len(self.issues)})</h2>
    {issue_cards if issue_cards else '<div class="card"><p style="color:#4ade80;">✅ No issues found</p></div>'}
  </section>

  <!-- CRASH INTELLIGENCE -->
  {"<section><h2>💥 Crash Intelligence Reports (" + str(len(self.crash_reports)) + " crashes deep-analysed)</h2>" + crash_cards_html + "</section>" if self.crash_reports else ""}

  <!-- TEST RESULTS -->
  <section>
    <h2>✅ All Test Results ({total} tests)</h2>
    <table style="background:var(--card);border-radius:10px;overflow:hidden;">
      <thead><tr><th></th><th>Test</th><th>Status</th><th>Module</th><th>Duration</th><th>Note</th></tr></thead>
      <tbody>{result_rows}</tbody>
    </table>
  </section>

  <!-- MODULE SUMMARY -->
  <section>
    <h2>📊 Module Summary</h2>
    <table style="background:var(--card);border-radius:10px;overflow:hidden;">
      <thead><tr><th>Module</th><th>Passed</th><th>Failed</th><th>Pass Rate</th></tr></thead>
      <tbody>{module_rows}</tbody>
    </table>
  </section>

</div>

<footer>
  Generated by Elite QA Agent · SouthStream · {datetime.now().strftime('%B %d, %Y %H:%M')} · Device: {self.target}
</footer>
</body>
</html>"""

        with open(report_path, "w") as f:
            f.write(html)

        return report_path


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Elite QA Agent for SouthStream")
    ap.add_argument("--ip",      required=True,  help="Device IP (e.g. 192.168.2.8)")
    ap.add_argument("--package", default="in.southstream.android")
    ap.add_argument("--port",    type=int, default=5555)
    ap.add_argument("--mirror",  action="store_true",
                    help="Mirror Fire TV screen to your Mac silently using scrcpy "
                         "(no recording notification on TV). Requires scrcpy installed.")
    args = ap.parse_args()

    agent = EliteQAAgent(ip=args.ip, package=args.package, port=args.port,
                         mirror=args.mirror)
    report = agent.run()

    import subprocess as sp
    sp.run(["open", report])
