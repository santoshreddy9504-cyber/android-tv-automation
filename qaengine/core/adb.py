"""
Universal ADB Wrapper — works with any Android device / app.
"""
import subprocess, re, time
from typing import Optional, List


class ADB:
    def __init__(self, device: str):
        self.device = device  # IP:port or serial

    def _run(self, cmd: str, timeout: int = 10) -> str:
        try:
            r = subprocess.run(
                f"adb -s {self.device} {cmd}",
                shell=True, capture_output=True, text=True, timeout=timeout
            )
            return r.stdout.strip()
        except:
            return ""

    def connect(self) -> bool:
        out = subprocess.run(f"adb connect {self.device}", shell=True,
                             capture_output=True, text=True).stdout
        return "connected" in out or "already" in out

    def is_connected(self) -> bool:
        out = subprocess.run("adb devices", shell=True, capture_output=True, text=True).stdout
        return self.device in out

    def auto_reconnect(self) -> bool:
        """Check connection and reconnect if dropped. Returns True if connected."""
        if self.is_connected():
            return True
        return self.connect()

    def get_pid(self, package: str) -> Optional[str]:
        pid = self._run(f"shell pidof {package}").strip()
        return pid if pid else None

    def get_memory_mb(self, package: str) -> float:
        raw = self._run(f"shell dumpsys meminfo {package}")
        for line in raw.splitlines():
            if "TOTAL" in line:
                parts = line.split()
                if parts and parts[0].isdigit():
                    return round(int(parts[0]) / 1024, 1)
        return 0.0

    def get_cpu(self, package: str) -> float:
        raw = self._run(f"shell top -n 1 -b | grep {package}")
        match = re.search(r'(\d+\.?\d*)%', raw)
        return float(match.group(1)) if match else 0.0

    def get_battery(self) -> dict:
        """Return battery level (%) and temperature (°C)."""
        raw = self._run("shell dumpsys battery")
        level = 0
        temp  = 0.0
        for line in raw.splitlines():
            if "level:" in line:
                try: level = int(line.split(":")[1].strip())
                except: pass
            if "temperature:" in line:
                try: temp = round(int(line.split(":")[1].strip()) / 10.0, 1)
                except: pass
        return {"level": level, "temp_c": temp}

    def get_app_version(self, package: str) -> dict:
        """Return versionName and versionCode from dumpsys package."""
        raw = self._run(f"shell dumpsys package {package}")
        version_name = "?"
        version_code = "?"
        for line in raw.splitlines():
            if "versionName=" in line:
                try: version_name = line.strip().split("versionName=")[1].split()[0]
                except: pass
            if "versionCode=" in line:
                try: version_code = line.strip().split("versionCode=")[1].split()[0]
                except: pass
        return {"name": version_name, "code": version_code}

    def screenshot(self, local_path: str) -> bool:
        self._run("shell screencap -p /sdcard/__qa_ss.png")
        r = subprocess.run(
            f"adb -s {self.device} pull /sdcard/__qa_ss.png {local_path}",
            shell=True, capture_output=True
        )
        return r.returncode == 0

    def start_recording(self, remote_path: str = "/sdcard/__qa_rec.mp4",
                        time_limit: int = 180, bitrate: str = "4M") -> subprocess.Popen:
        cmd = (f"adb -s {self.device} shell screenrecord "
               f"--time-limit {time_limit} --bit-rate {bitrate} {remote_path}")
        return subprocess.Popen(cmd, shell=True)

    def pull_recording(self, remote_path: str, local_path: str) -> bool:
        r = subprocess.run(
            f"adb -s {self.device} pull {remote_path} {local_path}",
            shell=True, capture_output=True
        )
        return r.returncode == 0

    def clear_logcat(self):
        self._run("logcat -c")

    def logcat_stream(self, filters: List[str]) -> subprocess.Popen:
        filter_str = " ".join(filters)
        cmd = f"adb -s {self.device} logcat -v time {filter_str}"
        return subprocess.Popen(cmd, shell=True,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL,
                                text=True)

    def launch_app(self, package: str) -> bool:
        out = self._run(f"shell monkey -p {package} -c android.intent.category.LAUNCHER 1")
        return "Events injected" in out

    def force_stop(self, package: str):
        self._run(f"shell am force-stop {package}")

    def get_focused_activity(self) -> str:
        raw = self._run("shell dumpsys activity | grep mFocusedApp")
        return raw.strip()

    def wake_screen(self):
        self._run("shell input keyevent 26")
        time.sleep(0.5)

    def get_device_info(self) -> dict:
        return {
            "model":   self._run("shell getprop ro.product.model"),
            "brand":   self._run("shell getprop ro.product.brand"),
            "android": self._run("shell getprop ro.build.version.release"),
            "sdk":     self._run("shell getprop ro.build.version.sdk"),
            "serial":  self.device,
        }
