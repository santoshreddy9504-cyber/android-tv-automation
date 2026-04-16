"""
Device Fleet — Monitor multiple Android TV / Fire TV / Mobile devices simultaneously.

Runs independent monitoring sessions for each device in parallel threads.
Produces one unified cross-platform report.

Usage:
    fleet = DeviceFleet()
    fleet.add_device("Android TV", "192.168.2.29", "com.southstream.tv")
    fleet.add_device("Fire TV",    "192.168.2.8",  "com.southstream.tv")
    fleet.add_device("Mobile",     "192.168.2.15", "com.southstream.android")
    fleet.start()   # All devices monitored in parallel
    fleet.wait()
    report = fleet.generate_report()
"""

import logging
import threading
import time
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)


@dataclass
class DeviceConfig:
    """Configuration for one device in the fleet."""
    name: str                          # Human name: "Android TV", "Fire TV"
    ip: str                            # Device IP
    port: int = 5555
    package: str = ""                  # App package
    device_type: str = "android_tv"    # android_tv | fire_tv | mobile | tablet
    enabled: bool = True

    @property
    def adb_target(self) -> str:
        return f"{self.ip}:{self.port}"


@dataclass
class DeviceSession:
    """Live session data for one device."""
    device: DeviceConfig
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None

    # Collected metrics
    crash_count: int = 0
    restart_count: int = 0
    peak_memory_mb: float = 0.0
    avg_memory_mb: float = 0.0
    peak_cpu: float = 0.0
    peak_frame_drop_pct: float = 0.0

    # Events
    crashes: List[Dict] = field(default_factory=list)
    performance_readings: List[Dict] = field(default_factory=list)
    screenshots: List[str] = field(default_factory=list)

    # Status
    status: str = "starting"      # starting | running | stopped | error
    error_message: str = ""
    thread: Optional[threading.Thread] = None

    @property
    def duration_seconds(self) -> float:
        end = self.end_time or datetime.now()
        return (end - self.start_time).total_seconds()

    @property
    def crashes_per_hour(self) -> float:
        hours = max(self.duration_seconds / 3600, 0.01)
        return self.crash_count / hours


class DeviceFleet:
    """
    Manages parallel monitoring of multiple devices.

    Each device runs in its own thread with its own ADB connection,
    logcat stream, and performance monitor. Results are aggregated
    into one unified cross-platform report.
    """

    def __init__(self, duration_minutes: float = 60.0):
        self._devices: List[DeviceConfig] = []
        self._sessions: Dict[str, DeviceSession] = {}
        self._duration = duration_minutes * 60
        self._stop_event = threading.Event()
        self._executor: Optional[ThreadPoolExecutor] = None

    def add_device(
        self,
        name: str,
        ip: str,
        package: str,
        port: int = 5555,
        device_type: str = "android_tv",
    ) -> "DeviceFleet":
        """Add a device to the fleet. Returns self for chaining."""
        dev = DeviceConfig(
            name=name, ip=ip, port=port,
            package=package, device_type=device_type,
        )
        self._devices.append(dev)
        logger.info(f"Fleet: added {name} ({ip}:{port})")
        return self

    def start(self):
        """Start monitoring all devices in parallel."""
        if not self._devices:
            logger.error("No devices in fleet")
            return

        logger.info(f"Starting fleet monitoring — {len(self._devices)} device(s)")

        self._executor = ThreadPoolExecutor(
            max_workers=len(self._devices),
            thread_name_prefix="Fleet",
        )

        for dev in self._devices:
            if not dev.enabled:
                continue
            session = DeviceSession(device=dev)
            self._sessions[dev.name] = session
            session.thread = threading.Thread(
                target=self._monitor_device,
                args=(dev, session),
                name=f"Fleet-{dev.name}",
                daemon=True,
            )
            session.thread.start()

        logger.info("All fleet devices started")

    def wait(self):
        """Block until all sessions complete or stop signal received."""
        try:
            self._stop_event.wait(timeout=self._duration)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self):
        """Stop all device sessions."""
        self._stop_event.set()
        logger.info("Fleet stop signal sent")

    def _monitor_device(self, dev: DeviceConfig, session: DeviceSession):
        """Monitor one device — runs in its own thread."""
        logger.info(f"[{dev.name}] Starting monitor on {dev.adb_target}")
        session.status = "running"

        try:
            # Connect ADB
            if not self._adb_connect(dev):
                session.status = "error"
                session.error_message = f"Cannot connect to {dev.adb_target}"
                return

            # Start logcat reader
            logcat_thread = threading.Thread(
                target=self._read_logcat,
                args=(dev, session),
                daemon=True,
            )
            logcat_thread.start()

            # Poll performance
            while not self._stop_event.is_set():
                self._poll_performance(dev, session)
                self._stop_event.wait(timeout=30)

        except Exception as exc:
            logger.error(f"[{dev.name}] Monitor error: {exc}")
            session.status = "error"
            session.error_message = str(exc)
        finally:
            session.end_time = datetime.now()
            session.status = "stopped"
            self._adb_disconnect(dev)
            logger.info(f"[{dev.name}] Session ended — "
                        f"{session.crash_count} crashes, "
                        f"peak {session.peak_memory_mb:.0f}MB")

    def _adb_connect(self, dev: DeviceConfig) -> bool:
        try:
            result = subprocess.run(
                ["adb", "connect", dev.adb_target],
                capture_output=True, text=True, timeout=15,
            )
            return "connected" in result.stdout.lower()
        except Exception as exc:
            logger.error(f"[{dev.name}] ADB connect failed: {exc}")
            return False

    def _adb_disconnect(self, dev: DeviceConfig):
        try:
            subprocess.run(
                ["adb", "disconnect", dev.adb_target],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass

    def _adb_shell(self, dev: DeviceConfig, cmd: str) -> str:
        try:
            result = subprocess.run(
                ["adb", "-s", dev.adb_target, "shell", cmd],
                capture_output=True, text=True, timeout=10,
            )
            return result.stdout.strip()
        except Exception:
            return ""

    def _read_logcat(self, dev: DeviceConfig, session: DeviceSession):
        """Stream logcat and detect crashes."""
        import re
        crash_pattern = re.compile(
            r"FATAL EXCEPTION|AndroidRuntime.*Exception|ANR in|"
            r"Process.*has died|OutOfMemoryError|mqt_native_modules",
            re.IGNORECASE,
        )
        try:
            proc = subprocess.Popen(
                ["adb", "-s", dev.adb_target, "logcat", "-v", "threadtime"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True,
            )
            for line in proc.stdout:
                if self._stop_event.is_set():
                    break
                if crash_pattern.search(line) and dev.package in line:
                    session.crash_count += 1
                    session.crashes.append({
                        "timestamp": datetime.now().isoformat(),
                        "line": line.strip()[:200],
                        "crash_number": session.crash_count,
                    })
                    logger.warning(f"[{dev.name}] CRASH #{session.crash_count} detected")
            proc.terminate()
        except Exception as exc:
            logger.error(f"[{dev.name}] Logcat error: {exc}")

    def _poll_performance(self, dev: DeviceConfig, session: DeviceSession):
        """Poll memory and CPU for one device."""
        try:
            # Memory
            mem_out = self._adb_shell(dev, f"dumpsys meminfo {dev.package}")
            mem_mb = self._parse_memory(mem_out)

            # CPU
            pid_out = self._adb_shell(dev, f"pidof {dev.package}")
            pid = pid_out.strip().split()[0] if pid_out.strip() else ""
            cpu = 0.0
            if pid:
                top_out = self._adb_shell(dev, f"top -n 1 -p {pid}")
                cpu = self._parse_cpu(top_out)

            reading = {
                "timestamp": datetime.now().isoformat(),
                "memory_mb": mem_mb,
                "cpu_percent": cpu,
            }
            session.performance_readings.append(reading)

            # Update peaks
            if mem_mb > 0:
                session.peak_memory_mb = max(session.peak_memory_mb, mem_mb)
                all_mem = [r["memory_mb"] for r in session.performance_readings if r["memory_mb"] > 0]
                session.avg_memory_mb = sum(all_mem) / len(all_mem)
            if cpu > 0:
                session.peak_cpu = max(session.peak_cpu, cpu)

            logger.debug(f"[{dev.name}] Mem:{mem_mb:.0f}MB CPU:{cpu:.1f}%")

        except Exception as exc:
            logger.debug(f"[{dev.name}] Perf poll error: {exc}")

    def _parse_memory(self, dumpsys_output: str) -> float:
        import re
        for line in dumpsys_output.splitlines():
            if "TOTAL" in line or "TOTAL PSS" in line:
                nums = re.findall(r'\d+', line)
                if nums:
                    return int(nums[0]) / 1024  # KB to MB
        return 0.0

    def _parse_cpu(self, top_output: str) -> float:
        import re
        for line in top_output.splitlines():
            nums = re.findall(r'(\d+\.?\d*)%', line)
            if nums:
                return float(nums[0])
        return 0.0

    def generate_report(self) -> str:
        """Generate a unified HTML cross-platform comparison report."""
        from datetime import datetime
        sessions = list(self._sessions.values())

        rows = ""
        for s in sessions:
            crash_color = "#dc2626" if s.crash_count > 0 else "#16a34a"
            mem_color = "#dc2626" if s.peak_memory_mb > 400 else (
                "#ca8a04" if s.peak_memory_mb > 300 else "#16a34a"
            )
            rows += f"""
            <tr>
              <td style="padding:12px; font-weight:bold; color:#f8f8f2;">{s.device.name}</td>
              <td style="padding:12px; color:#8be9fd;">{s.device.ip}</td>
              <td style="padding:12px; color:#f8f8f2;">{s.device.package}</td>
              <td style="padding:12px; text-align:center; color:{crash_color}; font-weight:bold;">{s.crash_count}</td>
              <td style="padding:12px; text-align:center; color:{mem_color}; font-weight:bold;">{s.peak_memory_mb:.0f} MB</td>
              <td style="padding:12px; text-align:center; color:#f8f8f2;">{s.peak_cpu:.1f}%</td>
              <td style="padding:12px; text-align:center; color:#f8f8f2;">{s.duration_seconds/60:.1f} min</td>
              <td style="padding:12px; text-align:center;">
                <span style="background:{'#16a34a' if s.status=='stopped' else '#ca8a04'};
                      color:white; padding:2px 8px; border-radius:10px; font-size:12px;">
                  {s.status}
                </span>
              </td>
            </tr>"""

        html = f"""<!DOCTYPE html>
<html>
<head>
  <title>Fleet Monitor Report — {datetime.now().strftime('%Y-%m-%d %H:%M')}</title>
  <style>
    body {{ background:#13131f; color:#f8f8f2; font-family:sans-serif; padding:20px; }}
    table {{ width:100%; border-collapse:collapse; background:#1e1e2e; border-radius:8px; overflow:hidden; }}
    th {{ background:#2a2a3e; padding:12px; text-align:left; color:#bd93f9; font-size:12px; text-transform:uppercase; }}
    tr:nth-child(even) {{ background:#252535; }}
    h1 {{ color:#bd93f9; }}
    .stat {{ display:inline-block; background:#2a2a3e; border-radius:8px; padding:16px 24px;
             margin:8px; text-align:center; min-width:120px; }}
    .stat-num {{ font-size:28px; font-weight:bold; color:#f8f8f2; }}
    .stat-label {{ font-size:11px; color:#6272a4; margin-top:4px; }}
  </style>
</head>
<body>
  <h1>Multi-Device Fleet Monitor Report</h1>
  <p style="color:#6272a4;">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>

  <div style="margin:20px 0;">
    <div class="stat">
      <div class="stat-num">{len(sessions)}</div>
      <div class="stat-label">DEVICES MONITORED</div>
    </div>
    <div class="stat">
      <div class="stat-num" style="color:#dc2626;">{sum(s.crash_count for s in sessions)}</div>
      <div class="stat-label">TOTAL CRASHES</div>
    </div>
    <div class="stat">
      <div class="stat-num" style="color:#ffb86c;">{max((s.peak_memory_mb for s in sessions), default=0):.0f}MB</div>
      <div class="stat-label">PEAK MEMORY (ANY)</div>
    </div>
    <div class="stat">
      <div class="stat-num">{sum(s.duration_seconds for s in sessions)/60/max(len(sessions),1):.0f}min</div>
      <div class="stat-label">AVG SESSION</div>
    </div>
  </div>

  <table>
    <thead>
      <tr>
        <th>Device</th><th>IP</th><th>App</th><th>Crashes</th>
        <th>Peak RAM</th><th>Peak CPU</th><th>Duration</th><th>Status</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>

  <h2 style="color:#bd93f9; margin-top:32px;">Cross-Platform Analysis</h2>
  {"<p style='color:#ff5555;'>⚠ Same crash detected on all devices — this is a CODE-LEVEL bug, not device-specific.</p>"
   if all(s.crash_count > 0 for s in sessions) and len(sessions) > 1 else
   "<p style='color:#50fa7b;'>✓ Crashes not uniform across devices — may be device-specific.</p>"}
</body>
</html>"""
        return html

    @property
    def sessions(self) -> Dict[str, DeviceSession]:
        return self._sessions

    @property
    def total_crashes(self) -> int:
        return sum(s.crash_count for s in self._sessions.values())
