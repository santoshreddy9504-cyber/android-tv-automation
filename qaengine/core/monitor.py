"""
Universal Monitor v2 — All 8 improvements + 4 new features.

Original 8:
1. Auto screen detection
2. Network failure monitoring
3. Adaptive thresholds (learns baseline)
4. Event timeline
5. Crash deduplication
6. TV focus tracker
7. Steps to reproduce (keypress logging)
8. Build comparison support

New additions:
9.  CPU monitoring
10. Battery drain tracking
11. Memory leak detection (linear slope)
12. Crash recovery timing
"""
import threading, time, os, re, hashlib, subprocess
from datetime import datetime
from typing import Callable, List, Optional, Dict
from .adb import ADB


# ─────────────────────────────────────────────────────────────────────────────
# Event
# ─────────────────────────────────────────────────────────────────────────────

class MonitorEvent:
    def __init__(self, event_type: str, message: str, data: dict = None):
        self.type      = event_type
        self.message   = message
        self.data      = data or {}
        self.timestamp = datetime.now()
        self.elapsed   = 0  # filled by monitor

    def __str__(self):
        return f"[{self.timestamp.strftime('%H:%M:%S')}] [{self.type}] {self.message}"

    def to_dict(self):
        return {
            "time":    self.timestamp.strftime("%H:%M:%S"),
            "elapsed": self.elapsed,
            "type":    self.type,
            "message": self.message,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Universal Monitor
# ─────────────────────────────────────────────────────────────────────────────

class UniversalMonitor:

    BASELINE_WINDOW   = 120   # seconds to learn baseline memory
    LEAK_WINDOW       = 10    # number of samples to check for leak trend
    LEAK_SLOPE_MB     = 5.0   # MB/sample threshold to call it a leak

    def __init__(self, adb: ADB, package: str,
                 memory_interval: int = 20,
                 screenshot_interval: int = 120,
                 session_dir: str = "sessions/current"):

        self.adb          = adb
        self.package      = package
        self.mem_interval = memory_interval
        self.ss_interval  = screenshot_interval
        self.session_dir  = session_dir
        self.ss_dir       = os.path.join(session_dir, "screenshots")
        self.log_file     = os.path.join(session_dir, "logcat.txt")
        self.events_file  = os.path.join(session_dir, "events.txt")

        os.makedirs(self.ss_dir, exist_ok=True)

        # State
        self._running       = False
        self._start_time    = None
        self._callbacks: List[Callable] = []
        self._events: List[MonitorEvent] = []

        # Counters
        self._crash_count    = 0
        self._ss_count       = 0
        self._anr_count      = 0
        self._net_fails      = 0
        self._focus_issues   = 0
        self._content_issues = 0
        self._frame_drops    = 0

        # Memory
        self._prev_pid       = None
        self._peak_mem       = 0.0
        self._last_mem       = 0.0
        self._baseline_mem   = 0.0
        self._baseline_samples: List[float] = []
        self._baseline_set   = False
        self._mem_samples: List[float] = []     # all samples for leak detection
        self._leak_detected  = False

        # CPU
        self._last_cpu       = 0.0
        self._peak_cpu       = 0.0
        self._cpu_samples: List[float] = []

        # Battery
        self._battery_start  = 0
        self._battery_end    = 0
        self._temp_start     = 0.0
        self._temp_peak      = 0.0

        # Crash recovery
        self._crash_times: List[float] = []     # epoch time of each crash
        self._recovery_times: List[float] = []  # seconds to recover per crash
        self._last_crash_epoch = None

        # Screen tracking
        self._current_screen = "Unknown"
        self._screen_history: List[str] = []

        # Crash deduplication
        self._crash_signatures: Dict[str, int] = {}  # hash → count

        # Steps to reproduce
        self._steps: List[str] = []
        self._key_proc = None

        # Network failures
        self._net_errors: List[dict] = []

        # Focus events
        self._focus_events: List[str] = []

        # Timeline (all events in order)
        self._timeline: List[dict] = []

        self._logcat_proc = None

    # ── Public API ─────────────────────────────────────────────────────────────

    def on_event(self, callback: Callable[[MonitorEvent], None]):
        self._callbacks.append(callback)

    def start(self):
        self._running    = True
        self._start_time = time.time()
        self.adb.clear_logcat()

        # Battery at start
        batt = self.adb.get_battery()
        self._battery_start = batt["level"]
        self._temp_start    = batt["temp_c"]

        self._emit("INFO", f"Session started — monitoring {self.package} | Battery: {self._battery_start}%")

        threads = [
            threading.Thread(target=self._memory_loop,     daemon=True, name="mem"),
            threading.Thread(target=self._cpu_loop,        daemon=True, name="cpu"),
            threading.Thread(target=self._logcat_loop,     daemon=True, name="logcat"),
            threading.Thread(target=self._screenshot_loop, daemon=True, name="ss"),
            threading.Thread(target=self._screen_loop,     daemon=True, name="screen"),
            threading.Thread(target=self._keylog_loop,     daemon=True, name="keys"),
            threading.Thread(target=self._reconnect_loop,  daemon=True, name="reconnect"),
        ]
        for t in threads:
            t.start()

    def stop(self):
        self._running = False
        if self._logcat_proc:
            try: self._logcat_proc.terminate()
            except: pass
        if self._key_proc:
            try: self._key_proc.terminate()
            except: pass

        # Battery at end
        batt = self.adb.get_battery()
        self._battery_end = batt["level"]

        self._emit("INFO",
                   f"Session stopped. Crashes:{self._crash_count} ANR:{self._anr_count} "
                   f"RAM:{self._peak_mem}MB CPU:{self._peak_cpu}% "
                   f"Battery:{self._battery_start}%→{self._battery_end}%")

    def take_screenshot(self, label: str = "auto") -> Optional[str]:
        self._ss_count += 1
        ts         = datetime.now().strftime("%H%M%S")
        screen_tag = self._current_screen.replace(" ", "_").replace("→", "_")[:20]
        fname      = f"{label}_{screen_tag}_{ts}.png"
        path       = os.path.join(self.ss_dir, fname)
        if self.adb.screenshot(path):
            self._emit("SCREENSHOT", f"Screenshot: {fname} | Screen: {self._current_screen}")
            return path
        return None

    def summary(self) -> dict:
        elapsed = int(time.time() - self._start_time) if self._start_time else 0
        crashes  = [e for e in self._events if e.type == "CRASH"]

        # Battery drain rate
        drain_total = self._battery_start - self._battery_end
        drain_per_hour = round((drain_total / elapsed * 3600), 1) if elapsed > 0 else 0

        # Avg CPU
        avg_cpu = round(sum(self._cpu_samples) / len(self._cpu_samples), 1) if self._cpu_samples else 0.0

        # QA Score
        qa_score = self._compute_qa_score()

        return {
            "package":          self.package,
            "duration_sec":     elapsed,
            "duration_str":     f"{elapsed//60}m {elapsed%60}s",
            "crashes":          self._crash_count,
            "unique_crashes":   len(self._crash_signatures),
            "crash_times":      [e.timestamp.strftime("%H:%M:%S") for e in crashes],
            "anrs":             self._anr_count,
            "net_failures":     self._net_fails,
            "focus_issues":     self._focus_issues,
            "content_issues":   self._content_issues,
            "frame_drops":      self._frame_drops,
            "peak_mem_mb":      self._peak_mem,
            "baseline_mem_mb":  self._baseline_mem,
            "last_mem_mb":      self._last_mem,
            "mem_samples":      self._mem_samples,
            "leak_detected":    self._leak_detected,
            "peak_cpu":         self._peak_cpu,
            "avg_cpu":          avg_cpu,
            "cpu_samples":      self._cpu_samples,
            "battery_start":    self._battery_start,
            "battery_end":      self._battery_end,
            "battery_drain":    drain_total,
            "drain_per_hour":   drain_per_hour,
            "temp_start":       self._temp_start,
            "temp_peak":        self._temp_peak,
            "recovery_times":   self._recovery_times,
            "avg_recovery_sec": round(sum(self._recovery_times)/len(self._recovery_times), 1)
                                 if self._recovery_times else 0,
            "screenshots":      self._ss_count,
            "screens_visited":  list(dict.fromkeys(self._screen_history)),
            "steps":            self._steps[-50:],
            "net_errors":       self._net_errors[-10:],
            "focus_events":     self._focus_events[-10:],
            "timeline":         self._timeline,
            "events":           [str(e) for e in self._events],
            "session_dir":      self.session_dir,
            "qa_score":         qa_score,
        }

    def _compute_qa_score(self) -> int:
        """
        QA Score 0–100.
        Start at 100, deduct for every issue found.
        """
        score = 100
        score -= self._crash_count  * 15   # -15 per crash
        score -= self._anr_count    * 10   # -10 per ANR
        score -= self._net_fails    * 3    # -3 per network error
        score -= self._focus_issues * 2    # -2 per focus issue
        score -= self._frame_drops  * 1    # -1 per frame drop event
        if self._leak_detected:
            score -= 10                    # -10 for memory leak
        if self._baseline_mem > 0 and self._peak_mem > self._baseline_mem * 2.0:
            score -= 10                    # -10 for sustained critical memory
        return max(0, min(100, score))

    # ── NEW: CPU Loop ─────────────────────────────────────────────────────────

    def _cpu_loop(self):
        while self._running:
            try:
                cpu = self.adb.get_cpu(self.package)
                if cpu >= 0:
                    self._last_cpu = cpu
                    self._peak_cpu = max(self._peak_cpu, cpu)
                    self._cpu_samples.append(cpu)

                    with open(os.path.join(self.session_dir, "cpu.txt"), "a") as f:
                        f.write(f"{datetime.now().strftime('%H:%M:%S')} CPU={cpu}% SCREEN={self._current_screen}\n")

                    if cpu > 80:
                        self._emit("PERF", f"High CPU: {cpu}% | Screen: {self._current_screen}",
                                   {"cpu": cpu, "screen": self._current_screen})
            except:
                pass
            time.sleep(self.mem_interval)

    # ── NEW: Auto-reconnect Loop ──────────────────────────────────────────────

    def _reconnect_loop(self):
        """Check device connection every 30 seconds, auto-reconnect if lost."""
        time.sleep(30)   # first check after 30s
        while self._running:
            try:
                if not self.adb.is_connected():
                    self._emit("INFO", "Device disconnected — attempting reconnect...")
                    if self.adb.auto_reconnect():
                        self._emit("INFO", "Reconnected successfully.")
                    else:
                        self._emit("INFO", "Reconnect failed — retrying in 30s...")
            except:
                pass
            time.sleep(30)

    # ── IMPROVEMENT 1: Auto Screen Detection ──────────────────────────────────

    def _screen_loop(self):
        """Poll current foreground Activity every 3 seconds."""
        while self._running:
            try:
                raw = self.adb._run("shell dumpsys window | grep mCurrentFocus")
                m   = re.search(r'(\w+)/(\S+)\}', raw)
                if m:
                    activity = m.group(2).split(".")[-1].replace("Activity", "")
                    if activity != self._current_screen:
                        self._current_screen = activity
                        self._screen_history.append(activity)
                        self._add_step(f"Screen changed → {activity}")
            except:
                pass
            time.sleep(3)

    # ── IMPROVEMENT 7: Keypress Logging (Steps to Reproduce) ─────────────────

    def _keylog_loop(self):
        """Capture remote control keypresses via ADB getevent."""
        try:
            cmd = f"adb -s {self.adb.device} shell getevent -l"
            self._key_proc = subprocess.Popen(cmd, shell=True,
                                              stdout=subprocess.PIPE,
                                              stderr=subprocess.DEVNULL,
                                              text=True)
            key_map = {
                "KEY_DPAD_UP":     "↑",
                "KEY_DPAD_DOWN":   "↓",
                "KEY_DPAD_LEFT":   "←",
                "KEY_DPAD_RIGHT":  "→",
                "KEY_DPAD_CENTER": "SELECT",
                "KEY_BACK":        "BACK",
                "KEY_MENU":        "MENU",
                "KEY_HOME":        "HOME",
                "KEY_ENTER":       "ENTER",
                "KEY_SEARCH":      "SEARCH",
            }
            for line in self._key_proc.stdout:
                if not self._running:
                    break
                for key, label in key_map.items():
                    if key in line and "DOWN" in line:
                        ts   = datetime.now().strftime("%H:%M:%S")
                        step = f"[{ts}] {label} on {self._current_screen}"
                        self._steps.append(step)
                        if len(self._steps) > 100:
                            self._steps.pop(0)
        except:
            pass

    # ── IMPROVEMENT 3: Adaptive Threshold Memory Loop ─────────────────────────

    def _memory_loop(self):
        while self._running:
            try:
                mem = self.adb.get_memory_mb(self.package)
                pid = self.adb.get_pid(self.package)

                if mem > 0:
                    self._last_mem = mem
                    self._peak_mem = max(self._peak_mem, mem)
                    self._mem_samples.append(mem)

                    # Learn baseline in first 2 minutes
                    elapsed = time.time() - self._start_time
                    if not self._baseline_set:
                        if elapsed < self.BASELINE_WINDOW:
                            self._baseline_samples.append(mem)
                        else:
                            if self._baseline_samples:
                                self._baseline_mem = round(
                                    sum(self._baseline_samples) / len(self._baseline_samples), 1)
                            self._baseline_set = True
                            self._emit("INFO", f"Baseline memory set: {self._baseline_mem}MB")

                    # Adaptive thresholds
                    if self._baseline_set and self._baseline_mem > 0:
                        ratio = mem / self._baseline_mem
                        if ratio > 2.0:
                            self._emit("MEMORY",
                                       f"CRITICAL RAM: {mem}MB — {ratio:.1f}x baseline ({self._baseline_mem}MB) | Screen: {self._current_screen}",
                                       {"mem_mb": mem, "ratio": ratio, "screen": self._current_screen})
                            # Smart screenshot on critical memory
                            self.take_screenshot(f"MEM_CRITICAL_{int(mem)}MB")
                        elif ratio > 1.5:
                            self._emit("MEMORY",
                                       f"High RAM: {mem}MB — {ratio:.1f}x baseline | Screen: {self._current_screen}",
                                       {"mem_mb": mem, "ratio": ratio, "screen": self._current_screen})
                    else:
                        if mem > 450:
                            self._emit("MEMORY", f"CRITICAL RAM: {mem}MB", {"mem_mb": mem})
                            self.take_screenshot(f"MEM_CRITICAL_{int(mem)}MB")
                        elif mem > 350:
                            self._emit("MEMORY", f"High RAM: {mem}MB", {"mem_mb": mem})

                    # NEW: Memory leak detection
                    self._check_memory_leak()

                    # Write memory log
                    with open(os.path.join(self.session_dir, "memory.txt"), "a") as f:
                        f.write(f"{datetime.now().strftime('%H:%M:%S')} "
                                f"MEM={mem}MB PID={pid} SCREEN={self._current_screen}\n")

                # Battery temperature tracking
                batt = self.adb.get_battery()
                self._temp_peak = max(self._temp_peak, batt["temp_c"])

                # Crash detection via PID change
                if self._prev_pid and pid and pid != self._prev_pid:
                    self._handle_crash(mem, pid)
                elif self._last_crash_epoch and pid:
                    # App came back — measure recovery time
                    recovery_sec = round(time.time() - self._last_crash_epoch, 1)
                    self._recovery_times.append(recovery_sec)
                    self._emit("INFO", f"App recovered in {recovery_sec}s after crash | New PID: {pid}")
                    self._last_crash_epoch = None

                if pid:
                    self._prev_pid = pid

            except:
                pass
            time.sleep(self.mem_interval)

    def _check_memory_leak(self):
        """Linear slope check on last N memory samples to detect leak."""
        if self._leak_detected:
            return
        samples = self._mem_samples[-self.LEAK_WINDOW:]
        if len(samples) < self.LEAK_WINDOW:
            return

        # Simple linear regression slope
        n     = len(samples)
        xs    = list(range(n))
        x_avg = sum(xs) / n
        y_avg = sum(samples) / n
        num   = sum((xs[i] - x_avg) * (samples[i] - y_avg) for i in range(n))
        den   = sum((xs[i] - x_avg) ** 2 for i in range(n))
        slope = num / den if den != 0 else 0

        if slope > self.LEAK_SLOPE_MB:
            self._leak_detected = True
            self._emit("MEMORY",
                       f"MEMORY LEAK DETECTED — rising {slope:.1f}MB/sample over last {n} readings | "
                       f"Current: {self._last_mem}MB | Screen: {self._current_screen}",
                       {"slope": slope, "screen": self._current_screen, "leak": True})
            self.take_screenshot("MEMORY_LEAK")

    def _handle_crash(self, mem: float, new_pid: str):
        """Detect crash, deduplicate, record steps, measure recovery time."""
        sig = self._get_crash_signature()
        self._last_crash_epoch = time.time()

        if sig in self._crash_signatures:
            self._crash_signatures[sig] += 1
            count = self._crash_signatures[sig]
            self._emit("CRASH",
                       f"CRASH #{self._crash_count+1} — DUPLICATE (seen {count}x) | "
                       f"Screen: {self._current_screen} | RAM: {mem}MB",
                       {"duplicate": True, "count": count, "screen": self._current_screen,
                        "mem_mb": mem, "steps": list(self._steps[-10:])})
        else:
            self._crash_count += 1
            self._crash_signatures[sig] = 1
            steps_snapshot = list(self._steps[-10:])
            self._emit("CRASH",
                       f"CRASH #{self._crash_count} | Screen: {self._current_screen} | RAM: {mem}MB",
                       {"crash_num": self._crash_count, "screen": self._current_screen,
                        "mem_mb": mem, "steps": steps_snapshot, "sig": sig})
            self.take_screenshot(f"CRASH_{self._crash_count}")

            steps_file = os.path.join(self.session_dir, f"steps_crash{self._crash_count}.txt")
            with open(steps_file, "w") as f:
                f.write(f"CRASH #{self._crash_count} — Steps to Reproduce\n")
                f.write(f"Screen: {self._current_screen}\n")
                f.write(f"RAM at crash: {mem}MB\n\n")
                f.write("Last 10 actions before crash:\n")
                for i, s in enumerate(steps_snapshot, 1):
                    f.write(f"  {i}. {s}\n")

    def _get_crash_signature(self) -> str:
        try:
            if not os.path.exists(self.log_file):
                return "unknown"
            with open(self.log_file) as f:
                lines = f.readlines()
            sig_lines = []
            in_fatal  = False
            for line in reversed(lines[-100:]):
                if "FATAL EXCEPTION" in line:
                    in_fatal = True
                if in_fatal:
                    sig_lines.append(line.strip())
                    if len(sig_lines) > 5:
                        break
            sig_text = "".join(reversed(sig_lines))
            return hashlib.md5(sig_text.encode()).hexdigest()[:8]
        except:
            return "unknown"

    # ── IMPROVEMENT 2: Network Failure Monitoring ─────────────────────────────

    def _logcat_loop(self):
        filters = [
            "ReactNativeJS:V",
            "AndroidRuntime:E",
            "ActivityManager:I",
            "Choreographer:W",
            "OkHttp:D",
            "Retrofit:D",
            "Network:E",
            "Volley:E",
        ]
        self._logcat_proc = self.adb.logcat_stream(filters)

        with open(self.log_file, "w") as logf:
            for line in self._logcat_proc.stdout:
                if not self._running:
                    break
                line = line.strip()
                if not line:
                    continue
                logf.write(line + "\n")
                logf.flush()
                self._analyze_logline(line)

    def _analyze_logline(self, line: str):
        low = line.lower()

        if "fatal exception" in low:
            self._emit("CRASH", f"FATAL in logcat: {line[:120]}",
                       {"raw": line, "screen": self._current_screen})

        elif "anr in" in low and self.package in line:
            self._anr_count += 1
            self._emit("ANR", f"ANR #{self._anr_count} | Screen: {self._current_screen} | {line[:80]}",
                       {"raw": line, "screen": self._current_screen})
            self.take_screenshot(f"ANR_{self._anr_count}")

        elif "choreographer" in low:
            m = re.search(r"skipped (\d+) frames", line)
            if m and int(m.group(1)) > 30:
                self._frame_drops += 1
                self._emit("PERF", f"Frame drop: {m.group(1)} frames skipped | Screen: {self._current_screen}",
                           {"frames": m.group(1), "screen": self._current_screen})

        elif any(x in low for x in ["http 4", "http 5", "connection refused",
                                    "sockettimeout", "connect failed",
                                    "unable to resolve host", "network error",
                                    "javax.net.ssl", "failed to connect"]):
            self._net_fails += 1
            err = {"time": datetime.now().strftime("%H:%M:%S"),
                   "screen": self._current_screen, "error": line[20:120]}
            self._net_errors.append(err)
            self._emit("NETWORK",
                       f"Network failure #{self._net_fails} | {line[20:80]} | Screen: {self._current_screen}",
                       err)

        elif any(x in low for x in ["undefined", "https://undefined", "null reference",
                                     "cannot read", "is not a function", "episodes: undefined"]):
            self._content_issues += 1
            self._emit("CONTENT", f"Missing content: {line[20:100]} | Screen: {self._current_screen}",
                       {"raw": line, "screen": self._current_screen})

        elif any(x in low for x in ["focus", "viewrootimpl", "inputdispatcher"]):
            if self.package in line or any(x in low for x in ["no focused", "lost focus", "focus leaving"]):
                self._focus_issues += 1
                ev = f"{datetime.now().strftime('%H:%M:%S')} {line[20:80]}"
                self._focus_events.append(ev)
                if "no focused" in low or "lost" in low:
                    self._emit("FOCUS",
                               f"Focus lost/missing | Screen: {self._current_screen} | {line[20:80]}",
                               {"screen": self._current_screen})

        elif "activitymanager" in low and "start" in low and self.package in line:
            self._emit("LOG", f"App launched | Screen: {self._current_screen}")

    # ── Screenshot loop ───────────────────────────────────────────────────────

    def _screenshot_loop(self):
        count = 0
        while self._running:
            time.sleep(self.ss_interval)
            if not self._running:
                break
            count += 1
            self.take_screenshot(f"auto_{count:02d}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _add_step(self, step: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self._steps.append(f"[{ts}] {step}")
        if len(self._steps) > 100:
            self._steps.pop(0)

    def _emit(self, event_type: str, message: str, data: dict = None):
        event         = MonitorEvent(event_type, message, data)
        event.elapsed = int(time.time() - self._start_time) if self._start_time else 0
        self._events.append(event)
        self._timeline.append(event.to_dict())

        with open(self.events_file, "a") as f:
            f.write(str(event) + "\n")

        for cb in self._callbacks:
            try:
                cb(event)
            except:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# IMPROVEMENT 7: Build Comparison
# ─────────────────────────────────────────────────────────────────────────────

def compare_builds(session_a: dict, session_b: dict,
                   label_a: str = "Build A", label_b: str = "Build B") -> dict:
    """
    Compare two session summaries and return diff.
    session_a = older build, session_b = newer build.
    """
    def delta(a, b):
        if a == 0:
            return "N/A"
        diff = b - a
        pct  = (diff / a) * 100
        sign = "+" if diff > 0 else ""
        return f"{sign}{diff:.1f} ({sign}{pct:.0f}%)"

    def verdict(a, b, lower_is_better=True):
        if lower_is_better:
            if b < a:   return "IMPROVED", "#4caf50"
            elif b > a: return "REGRESSED", "#e50914"
            else:       return "SAME", "#888"
        else:
            if b > a:   return "IMPROVED", "#4caf50"
            elif b < a: return "REGRESSED", "#e50914"
            else:       return "SAME", "#888"

    crashes_a = session_a.get("crashes", 0)
    crashes_b = session_b.get("crashes", 0)
    mem_a     = session_a.get("peak_mem_mb", 0)
    mem_b     = session_b.get("peak_mem_mb", 0)
    anr_a     = session_a.get("anrs", 0)
    anr_b     = session_b.get("anrs", 0)
    net_a     = session_a.get("net_failures", 0)
    net_b     = session_b.get("net_failures", 0)
    focus_a   = session_a.get("focus_issues", 0)
    focus_b   = session_b.get("focus_issues", 0)
    cpu_a     = session_a.get("peak_cpu", 0)
    cpu_b     = session_b.get("peak_cpu", 0)
    score_a   = session_a.get("qa_score", 0)
    score_b   = session_b.get("qa_score", 0)

    screens_a = set(session_a.get("screens_visited", []))
    screens_b = set(session_b.get("screens_visited", []))

    return {
        "label_a": label_a,
        "label_b": label_b,
        "metrics": [
            {"name": "QA Score",       "a": f"{score_a}/100", "b": f"{score_b}/100",
             "delta": delta(score_a, score_b),
             **dict(zip(["verdict","color"], verdict(score_a, score_b, lower_is_better=False)))},
            {"name": "Crashes",        "a": crashes_a, "b": crashes_b,
             "delta": delta(crashes_a, crashes_b),
             **dict(zip(["verdict","color"], verdict(crashes_a, crashes_b)))},
            {"name": "Peak Memory",    "a": f"{mem_a}MB", "b": f"{mem_b}MB",
             "delta": delta(mem_a, mem_b),
             **dict(zip(["verdict","color"], verdict(mem_a, mem_b)))},
            {"name": "ANRs",           "a": anr_a, "b": anr_b,
             "delta": delta(anr_a, anr_b),
             **dict(zip(["verdict","color"], verdict(anr_a, anr_b)))},
            {"name": "Network Errors", "a": net_a, "b": net_b,
             "delta": delta(net_a, net_b),
             **dict(zip(["verdict","color"], verdict(net_a, net_b)))},
            {"name": "Focus Issues",   "a": focus_a, "b": focus_b,
             "delta": delta(focus_a, focus_b),
             **dict(zip(["verdict","color"], verdict(focus_a, focus_b)))},
            {"name": "Peak CPU",       "a": f"{cpu_a}%", "b": f"{cpu_b}%",
             "delta": delta(cpu_a, cpu_b),
             **dict(zip(["verdict","color"], verdict(cpu_a, cpu_b)))},
        ],
        "new_screens":     list(screens_b - screens_a),
        "dropped_screens": list(screens_a - screens_b),
        "overall": "IMPROVED" if score_b > score_a else
                   "REGRESSED" if score_b < score_a else "SAME",
    }
