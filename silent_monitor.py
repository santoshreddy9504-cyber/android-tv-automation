#!/usr/bin/env python3
"""
Silent Monitor — Fire TV QA
Covers: crashes, memory, card loading time, focus issues, missing content, ANR, frame drops
"""

import subprocess, threading, time, os, re, signal, sys
from datetime import datetime

# ── Config ──────────────────────────────────────────────────────────────────
PKG        = "in.southstream.android"
SESSION_DIR = "output/monitor_session/apr15_newbuild"
SS_DIR      = "output/screenshots/apr15_newbuild"
SESSION_START = time.time()

os.makedirs(SESSION_DIR, exist_ok=True)
os.makedirs(SS_DIR, exist_ok=True)

EVENTS_FILE = os.path.join(SESSION_DIR, "events.txt")
MEM_FILE    = os.path.join(SESSION_DIR, "memory.txt")
LOGCAT_FILE = os.path.join(SESSION_DIR, "logcat.txt")

# ── Helpers ──────────────────────────────────────────────────────────────────
def ts():
    return datetime.now().strftime("%H:%M:%S")

def elapsed():
    s = int(time.time() - SESSION_START)
    return f"{s//60}m {s%60}s"

def log_event(msg, category="INFO"):
    line = f"[{ts()}] [{elapsed()}] [{category}] {msg}"
    print(line)
    with open(EVENTS_FILE, "a") as f:
        f.write(line + "\n")

def adb(cmd):
    try:
        r = subprocess.run(f"adb {cmd}", shell=True, capture_output=True, text=True, timeout=10)
        return r.stdout.strip()
    except:
        return ""

def screenshot(label):
    fname = f"{label}_{ts().replace(':','')}.png"
    path  = os.path.join(SS_DIR, fname)
    adb(f"shell screencap -p /sdcard/ss_tmp.png")
    adb(f"pull /sdcard/ss_tmp.png {path}")
    log_event(f"Screenshot saved: {fname}", "SCREENSHOT")
    return fname

# ── State ────────────────────────────────────────────────────────────────────
state = {
    "crashes"        : 0,
    "anr"            : 0,
    "focus_issues"   : 0,
    "missing_content": 0,
    "frame_drops"    : 0,
    "prev_pid"       : None,
    "peak_mem"       : 0,
    "last_mem"       : 0,
    "auto_ss_count"  : 0,
    "loading_events" : [],
    "focus_events"   : [],
    "missing_events" : [],
    "crash_times"    : [],
}

# ── Thread 1: Memory + Crash Detection (every 15s) ───────────────────────────
def memory_thread():
    log_event("Memory monitor started", "INIT")
    while True:
        try:
            mem_raw = adb(f"shell dumpsys meminfo {PKG}")
            mem_kb  = 0
            for line in mem_raw.splitlines():
                if "TOTAL" in line:
                    parts = line.split()
                    if parts and parts[0].isdigit():
                        mem_kb = int(parts[0])
                        break
            mem_mb = round(mem_kb / 1024, 1) if mem_kb else 0

            cur_pid = adb(f"shell pidof {PKG}").strip()

            if mem_mb > 0:
                state["last_mem"] = mem_mb
                state["peak_mem"] = max(state["peak_mem"], mem_mb)

                with open(MEM_FILE, "a") as f:
                    f.write(f"{ts()}  MEM={mem_mb}MB  PID={cur_pid}  ELAPSED={elapsed()}\n")

                # Warn on high memory
                if mem_mb > 400:
                    log_event(f"HIGH MEMORY: {mem_mb}MB (peak={state['peak_mem']}MB)", "MEMORY_WARN")
                elif mem_mb > 300:
                    log_event(f"Memory: {mem_mb}MB", "MEMORY")

            # Crash = PID changed
            if state["prev_pid"] and cur_pid and cur_pid != state["prev_pid"]:
                state["crashes"] += 1
                crash_time = ts()
                state["crash_times"].append(crash_time)
                log_event(
                    f"CRASH #{state['crashes']} — PID {state['prev_pid']} → {cur_pid} | mem was {mem_mb}MB",
                    "CRASH"
                )
                screenshot(f"crash_{state['crashes']}")

            if cur_pid:
                state["prev_pid"] = cur_pid

        except Exception as e:
            pass
        time.sleep(15)

# ── Thread 2: Logcat Analysis ─────────────────────────────────────────────────
def logcat_thread():
    log_event("Logcat monitor started", "INIT")
    cmd = [
        "adb", "logcat", "-v", "time",
        "ReactNativeJS:V",
        "AndroidRuntime:E",
        "ActivityManager:I",
        "Choreographer:W",
        "InputDispatcher:W",
        "ViewRootImpl:W",
        "WindowManager:W",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

    # Track loading start times
    loading_starts = {}

    with open(LOGCAT_FILE, "w") as logf:
        for raw_line in proc.stdout:
            line = raw_line.strip()
            if not line:
                continue
            logf.write(line + "\n")
            logf.flush()

            # ── Crash / Fatal ──
            if "FATAL EXCEPTION" in line or "AndroidRuntime" in line and "FATAL" in line:
                state["crashes"] += 1
                log_event(f"FATAL EXCEPTION in logcat: {line[:120]}", "CRASH")
                screenshot(f"fatal_{state['crashes']}")

            # ── ANR ──
            elif "ANR in" in line and PKG in line:
                state["anr"] += 1
                log_event(f"ANR #{state['anr']}: {line[:120]}", "ANR")
                screenshot(f"anr_{state['anr']}")

            # ── Frame Drops ──
            elif "Choreographer" in line and "skipped" in line:
                m = re.search(r"skipped (\d+) frames", line)
                if m and int(m.group(1)) > 30:
                    state["frame_drops"] += 1
                    log_event(f"FRAME DROP: {m.group(1)} frames skipped", "PERF")

            # ── Focus Issues ──
            elif any(x in line for x in ["Focus leaving", "Focus entering", "No focused window", "not focused"]):
                if PKG in line or "southstream" in line.lower():
                    state["focus_issues"] += 1
                    event = f"Focus issue: {line[20:100]}"
                    state["focus_events"].append(f"{ts()} {event}")
                    log_event(event, "FOCUS")

            # ── Missing / Undefined Content ──
            elif "ReactNativeJS" in line:
                low = line.lower()
                if any(x in low for x in ["undefined", "null", "cannot read", "episodes: undefined", "uri: 'https://undefined"]):
                    state["missing_content"] += 1
                    event = line[20:140]
                    state["missing_events"].append(f"{ts()} {event}")
                    log_event(f"MISSING CONTENT: {event}", "CONTENT")

                # ── Card / Screen Loading Time ──
                elif any(x in low for x in ["fetching", "loading", "api call", "request", "fetch started"]):
                    key = "screen"
                    loading_starts[key] = time.time()

                elif any(x in low for x in ["loaded", "rendered", "response", "success", "data received", "fetch complete"]):
                    key = "screen"
                    if key in loading_starts:
                        load_time = round(time.time() - loading_starts.pop(key), 2)
                        event = f"Load time: {load_time}s — {line[20:80]}"
                        state["loading_events"].append(f"{ts()} {event}")
                        if load_time > 3:
                            log_event(f"SLOW LOAD: {load_time}s", "PERF")
                        else:
                            log_event(event, "LOAD")

            # ── App start ──
            elif "ActivityManager" in line and "START" in line and PKG in line:
                log_event(f"App launched/restarted", "APP")
                loading_starts["launch"] = time.time()

            elif "ReactNativeJS" in line and "Running" in line and "SouthStream" in line:
                if "launch" in loading_starts:
                    launch_time = round(time.time() - loading_starts.pop("launch"), 2)
                    log_event(f"App ready in {launch_time}s", "PERF")
                else:
                    log_event("App JS bundle loaded", "APP")

# ── Thread 3: Auto Screenshot every 90s ──────────────────────────────────────
def screenshot_thread():
    log_event("Auto-screenshot monitor started (every 90s)", "INIT")
    while True:
        time.sleep(90)
        state["auto_ss_count"] += 1
        screenshot(f"auto_{state['auto_ss_count']:02d}")

# ── Thread 4: Live Summary every 5 min ───────────────────────────────────────
def summary_thread():
    while True:
        time.sleep(300)
        log_event(
            f"── SUMMARY ── elapsed={elapsed()} | crashes={state['crashes']} | "
            f"ANR={state['anr']} | focus={state['focus_issues']} | "
            f"missing_content={state['missing_content']} | frame_drops={state['frame_drops']} | "
            f"mem={state['last_mem']}MB peak={state['peak_mem']}MB",
            "SUMMARY"
        )

# ── Shutdown ──────────────────────────────────────────────────────────────────
def shutdown(sig=None, frame=None):
    print("\n")
    log_event("── FINAL REPORT ──", "END")
    log_event(f"Total session time : {elapsed()}", "END")
    log_event(f"Crashes detected   : {state['crashes']}", "END")
    log_event(f"ANRs               : {state['anr']}", "END")
    log_event(f"Focus issues       : {state['focus_issues']}", "END")
    log_event(f"Missing content    : {state['missing_content']}", "END")
    log_event(f"Frame drops (>30f) : {state['frame_drops']}", "END")
    log_event(f"Peak memory        : {state['peak_mem']}MB", "END")
    log_event(f"Auto screenshots   : {state['auto_ss_count']}", "END")

    if state["crash_times"]:
        log_event(f"Crash times: {', '.join(state['crash_times'])}", "END")
    if state["missing_events"]:
        log_event("Missing content events:", "END")
        for e in state["missing_events"][-5:]:
            log_event(f"  {e}", "END")
    if state["focus_events"]:
        log_event("Focus issues:", "END")
        for e in state["focus_events"][-5:]:
            log_event(f"  {e}", "END")
    if state["loading_events"]:
        log_event("Loading times:", "END")
        for e in state["loading_events"][-10:]:
            log_event(f"  {e}", "END")

    print(f"\nEvents log : {EVENTS_FILE}")
    print(f"Memory log : {MEM_FILE}")
    print(f"Logcat     : {LOGCAT_FILE}")
    print(f"Screenshots: {SS_DIR}/")
    sys.exit(0)

signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)

# ── Start ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    adb("logcat -c")
    log_event(f"=== SESSION STARTED — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===", "INIT")
    log_event(f"Package: {PKG}", "INIT")
    log_event("Monitoring: crashes | memory | ANR | frame drops | focus | missing content | card loading", "INIT")

    # Take start screenshot
    screenshot("session_start")

    threads = [
        threading.Thread(target=memory_thread,    daemon=True),
        threading.Thread(target=logcat_thread,    daemon=True),
        threading.Thread(target=screenshot_thread, daemon=True),
        threading.Thread(target=summary_thread,   daemon=True),
    ]
    for t in threads:
        t.start()

    print("\n✓ Silent monitor running. Press Ctrl+C to stop and get full report.\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown()
