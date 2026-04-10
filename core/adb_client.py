"""
ADB Client — low-level wrapper around ADB commands.
All subprocess calls go through here so the rest of the code stays clean.
"""

import subprocess
import threading
import time
import os
import logging
from typing import Optional, Iterator, List, Tuple

from config import config

logger = logging.getLogger(__name__)


class ADBError(Exception):
    """Raised when an ADB command fails."""


class ADBClient:
    """
    Wraps ADB CLI commands via subprocess.
    Supports WiFi connections, shell commands, logcat streaming,
    screenshots, and device metrics.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._connected = False
        self._device_target = config.device.adb_target
        self._logcat_process: Optional[subprocess.Popen] = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Connect to device over WiFi. Returns True on success."""
        target = config.device.adb_target
        logger.info(f"Connecting to {target} ...")

        for attempt in range(1, config.device.reconnect_retries + 1):
            try:
                result = self._run_adb(["connect", target], timeout=config.device.connection_timeout)
                output = result.stdout.strip()
                logger.debug(f"connect output: {output}")

                if "connected" in output.lower() or "already connected" in output.lower():
                    self._connected = True
                    logger.info(f"Connected to {target}")
                    return True

                logger.warning(f"Attempt {attempt}: unexpected response: {output}")
            except subprocess.TimeoutExpired:
                logger.warning(f"Attempt {attempt}: connection timed out")
            except Exception as exc:
                logger.warning(f"Attempt {attempt}: {exc}")

            if attempt < config.device.reconnect_retries:
                time.sleep(config.device.reconnect_delay)

        self._connected = False
        logger.error(f"Failed to connect to {target} after {config.device.reconnect_retries} attempts")
        return False

    def disconnect(self):
        """Gracefully disconnect from the device."""
        try:
            self.stop_logcat()
            self._run_adb(["disconnect", config.device.adb_target], timeout=5)
        except Exception:
            pass
        self._connected = False

    def is_connected(self) -> bool:
        """Quick liveness check — verify device is still in 'adb devices'."""
        try:
            result = self._run_adb(["devices"], timeout=5)
            return config.device.adb_target in result.stdout
        except Exception:
            return False

    def ensure_connected(self) -> bool:
        """Re-connect if connection dropped."""
        if self.is_connected():
            return True
        logger.warning("Device disconnected. Attempting reconnect...")
        return self.connect()

    # ------------------------------------------------------------------
    # Shell command execution
    # ------------------------------------------------------------------

    def shell(self, command: str, timeout: int = 30) -> str:
        """Run `adb shell <command>` and return stdout."""
        with self._lock:
            result = self._run_adb(
                ["-s", self._device_target, "shell", command],
                timeout=timeout
            )
            return result.stdout.strip()

    def shell_no_wait(self, command: str):
        """Fire-and-forget shell command (no output needed)."""
        subprocess.Popen(
            ["adb", "-s", self._device_target, "shell", command],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    # ------------------------------------------------------------------
    # Logcat streaming
    # ------------------------------------------------------------------

    def stream_logcat(self, clear_first: bool = True) -> Iterator[str]:
        """
        Generator that yields logcat lines as they arrive.
        Runs until stop_logcat() is called or process exits.
        """
        if clear_first:
            self._clear_logcat()

        cmd = ["adb", "-s", self._device_target, "logcat", "-v", "threadtime"]
        if config.monitor.logcat_tags:
            for tag in config.monitor.logcat_tags:
                cmd.append(tag)

        logger.debug(f"Starting logcat: {' '.join(cmd)}")
        self._logcat_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        try:
            for line in self._logcat_process.stdout:
                yield line.rstrip("\n")
        except (ValueError, OSError):
            # Process killed externally
            pass
        finally:
            self._logcat_process = None

    def stop_logcat(self):
        """Terminate the running logcat process."""
        if self._logcat_process and self._logcat_process.poll() is None:
            self._logcat_process.terminate()
            try:
                self._logcat_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._logcat_process.kill()
            self._logcat_process = None

    def _clear_logcat(self):
        """Clear the logcat ring buffer."""
        try:
            self._run_adb(["-s", self._device_target, "logcat", "-c"], timeout=10)
        except Exception as exc:
            logger.warning(f"Could not clear logcat: {exc}")

    # ------------------------------------------------------------------
    # Screenshot
    # ------------------------------------------------------------------

    def capture_screenshot(self, save_path: str) -> bool:
        """
        Capture device screenshot to save_path.
        Returns True on success.
        """
        try:
            remote_path = "/sdcard/automation_screenshot.png"
            self.shell(f"screencap -p {remote_path}", timeout=15)
            time.sleep(0.5)

            result = self._run_adb(
                ["-s", self._device_target, "pull", remote_path, save_path],
                timeout=20,
            )
            if "pulled" in result.stdout or os.path.exists(save_path):
                self.shell(f"rm {remote_path}")
                return True
        except Exception as exc:
            logger.error(f"Screenshot failed: {exc}")
        return False

    # ------------------------------------------------------------------
    # App info
    # ------------------------------------------------------------------

    def get_app_pid(self, package: str) -> Optional[int]:
        """Return PID of running package, or None if not running."""
        try:
            output = self.shell(f"pidof {package}")
            if output.strip().isdigit():
                return int(output.strip())
            # Fallback: parse ps output
            ps_out = self.shell(f"ps -A | grep {package}")
            for line in ps_out.splitlines():
                parts = line.split()
                if len(parts) > 1 and parts[-1] == package:
                    return int(parts[1])
        except Exception:
            pass
        return None

    def is_app_foreground(self, package: str) -> bool:
        """Return True if the package is currently in the foreground."""
        try:
            # Check window focus (works on most Android TV builds)
            output = self.shell(
                "dumpsys window windows | grep -E 'mCurrentFocus|mFocusedApp'"
            )
            if package in output:
                return True
            # Fallback: check resumed activity (more reliable on Android 12)
            output2 = self.shell(
                "dumpsys activity activities | grep -E 'mResumedActivity|topResumedActivity'"
            )
            return package in output2
        except Exception:
            return False

    def get_app_state(self, package: str) -> str:
        """Return 'running', 'stopped', or 'unknown'."""
        pid = self.get_app_pid(package)
        if pid:
            return "running"
        try:
            output = self.shell(f"am stack list | grep {package}")
            if output:
                return "running"
        except Exception:
            pass
        return "stopped"

    # ------------------------------------------------------------------
    # CPU / Memory
    # ------------------------------------------------------------------

    def get_cpu_usage(self, package: str) -> float:
        """
        Return CPU usage percentage for the package process.
        Uses 'top' with a single iteration.
        """
        try:
            output = self.shell(f"top -n 1 -b | grep {package}", timeout=10)
            for line in output.splitlines():
                if package in line:
                    parts = line.split()
                    # top format: PID USER PR NI ... %CPU ...
                    for part in parts:
                        try:
                            val = float(part.replace("%", ""))
                            if 0 < val <= 100:
                                return val
                        except ValueError:
                            continue
        except Exception as exc:
            logger.debug(f"CPU usage error: {exc}")
        return 0.0

    def get_memory_usage(self, package: str) -> Tuple[float, float]:
        """
        Return (used_mb, percent) for the package using dumpsys meminfo.
        """
        try:
            output = self.shell(f"dumpsys meminfo {package}", timeout=15)
            for line in output.splitlines():
                if "TOTAL" in line:
                    parts = line.split()
                    for part in parts:
                        try:
                            kb = int(part.replace(",", ""))
                            if kb > 0:
                                mb = kb / 1024.0
                                # Estimate percent from 2GB device
                                pct = (mb / 2048.0) * 100
                                return mb, min(pct, 100.0)
                        except ValueError:
                            continue
        except Exception as exc:
            logger.debug(f"Memory usage error: {exc}")
        return 0.0, 0.0

    def get_total_memory_mb(self) -> float:
        """Return total device RAM in MB."""
        try:
            output = self.shell("cat /proc/meminfo | grep MemTotal")
            for part in output.split():
                try:
                    return int(part) / 1024.0
                except ValueError:
                    continue
        except Exception:
            pass
        return 2048.0

    # ------------------------------------------------------------------
    # GFX info (frame drops)
    # ------------------------------------------------------------------

    def get_gfxinfo(self, package: str) -> dict:
        """
        Parse dumpsys gfxinfo for janky frames and render stats.
        Returns dict with keys: total_frames, janky_frames, frame_drop_pct
        """
        result = {"total_frames": 0, "janky_frames": 0, "frame_drop_pct": 0.0}
        try:
            output = self.shell(f"dumpsys gfxinfo {package}", timeout=15)
            for line in output.splitlines():
                line_lower = line.lower()
                if "total frames rendered" in line_lower:
                    parts = line.split()
                    result["total_frames"] = int(parts[-1])
                elif "janky frames" in line_lower:
                    parts = line.split()
                    for p in parts:
                        try:
                            val = int(p.split("(")[0])
                            result["janky_frames"] = val
                            break
                        except ValueError:
                            continue
            if result["total_frames"] > 0:
                result["frame_drop_pct"] = (
                    result["janky_frames"] / result["total_frames"]
                ) * 100
            # Reset stats for next poll
            self.shell(f"dumpsys gfxinfo {package} reset")
        except Exception as exc:
            logger.debug(f"gfxinfo error: {exc}")
        return result

    # ------------------------------------------------------------------
    # Device info
    # ------------------------------------------------------------------

    def get_device_info(self) -> dict:
        """Return basic device information."""
        info = {}
        try:
            info["model"] = self.shell("getprop ro.product.model")
            info["android_version"] = self.shell("getprop ro.build.version.release")
            info["sdk_version"] = self.shell("getprop ro.build.version.sdk")
            info["manufacturer"] = self.shell("getprop ro.product.manufacturer")
            info["serial"] = self.shell("getprop ro.serialno")
            info["total_memory_mb"] = self.get_total_memory_mb()
        except Exception as exc:
            logger.debug(f"Device info error: {exc}")
        return info

    def get_network_info(self) -> dict:
        """Return WiFi SSID and IP."""
        info = {}
        try:
            info["ssid"] = self.shell(
                "dumpsys wifi | grep 'mWifiInfo' | head -1"
            )
            info["ip"] = self.shell(
                "ip route | grep default | awk '{print $3}'"
            )
        except Exception:
            pass
        return info

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_adb(self, args: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
        """Execute `adb <args>` and return CompletedProcess."""
        cmd = ["adb"] + args
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0 and result.stderr:
            logger.debug(f"adb stderr: {result.stderr.strip()}")
        return result
