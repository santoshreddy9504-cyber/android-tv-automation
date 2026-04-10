"""
Logcat Monitor — streams adb logcat and dispatches lines to detectors.

This is the central monitor that reads every log line and passes it to
the specialised sub-detectors (crash, playback, network, UI).
"""

import logging
import re
import time
from collections import deque
from typing import List

from config import config
from monitors.base_monitor import BaseMonitor
from monitors.crash_detector import CrashDetector
from monitors.playback_monitor import PlaybackMonitor
from monitors.network_monitor import NetworkMonitor
from monitors.ui_monitor import UIMonitor
from monitors.api_monitor import APIMonitor

logger = logging.getLogger(__name__)

# Reference to TimingMonitor — injected after construction
_timing_monitor_ref = None
# Reference to APIMonitor — injected after construction
_api_monitor_ref = None

def register_timing_monitor(monitor):
    global _timing_monitor_ref
    _timing_monitor_ref = monitor

def register_api_monitor(monitor):
    global _api_monitor_ref
    _api_monitor_ref = monitor

# ---------------------------------------------------------------------------
# System-level noise filter — VU TV hardware / OS tags that produce
# high-volume errors unrelated to the app under test.
# Lines matching ANY of these are buffered but never sent to detectors.
# ---------------------------------------------------------------------------
_NOISE_TAGS = re.compile(
    r"\s+(?:"
    r"MI_PQ|PQ_HIDL|HuiVout|DLNA|"        # VU TV picture-quality chip + DLNA
    r"AudioFlinger|AudioTrack_C|"           # system audio internals
    r"Gralloc|gralloc|hwcomposer|HWC|"     # display/GPU HAL
    r"SurfaceFlinger|BufferQueueProducer|"  # display server
    r"chatty|Zygote|"                       # OS-level chattiness
    r"wpa_supplicant|WifiHAL|"             # WiFi driver noise
    r"BpBinder|IPCThreadState|"            # Binder internals
    r"SystemServer|ActivityManager_ANR|"   # exclude false ANR from syslog
    r"cast_shell|CastShell|mdns_app"       # Google Cast system process
    r")\s*:",
    re.IGNORECASE,
)


class LogcatMonitor(BaseMonitor):
    """
    Streams logcat in real time and fans each line out to detectors.
    Maintains a rolling buffer for context capture.
    """

    def __init__(self, session):
        super().__init__(session)
        self._buffer: deque = deque(maxlen=config.monitor.logcat_buffer_size)
        self._api_monitor = APIMonitor(session)
        self._detectors = [
            CrashDetector(session, self._buffer),
            PlaybackMonitor(session, self._buffer),
            NetworkMonitor(session, self._buffer),
            UIMonitor(session, self._buffer),
        ]
        # Auto-register so main.py / test_runner can access it
        register_api_monitor(self._api_monitor)

    @property
    def buffer(self) -> deque:
        """Read-only view of the rolling log buffer."""
        return self._buffer

    def run(self):
        """Stream logcat lines and route to detectors until stopped."""
        self._log.info("Logcat monitor starting ...")
        backoff = 2

        while not self._stop.is_set():
            try:
                if not self._adb.ensure_connected():
                    self._log.warning(f"Device not connected. Retrying in {backoff}s ...")
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 30)
                    continue

                backoff = 2  # reset on successful connect

                for line in self._adb.stream_logcat(clear_first=True):
                    if self._stop.is_set():
                        break

                    self._buffer.append(line)

                    # Timing monitor sees ALL lines (needs ActivityManager: Displayed)
                    if _timing_monitor_ref:
                        try:
                            _timing_monitor_ref.analyze(line)
                        except Exception as exc:
                            logger.debug(f"TimingMonitor error: {exc}")

                    # API monitor sees all lines (catches OkHttp / Retrofit output)
                    if _api_monitor_ref:
                        try:
                            _api_monitor_ref.analyze(line)
                        except Exception as exc:
                            logger.debug(f"APIMonitor error: {exc}")

                    # Skip known system noise for issue detectors only
                    if _NOISE_TAGS.search(line):
                        continue

                    self._route(line)

            except Exception as exc:
                if not self._stop.is_set():
                    self._log.error(f"Logcat stream error: {exc}. Restarting in {backoff}s ...")
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 30)

        self._log.info("Logcat monitor stopped.")

    def _route(self, line: str):
        """Pass logcat line to every registered detector."""
        for detector in self._detectors:
            try:
                detector.analyze(line)
            except Exception as exc:
                logger.debug(f"Detector {detector.__class__.__name__} error: {exc}")


    def get_context_lines(self, n: int = 50) -> List[str]:
        """Return the last n lines from the buffer (for log saving)."""
        return list(self._buffer)[-n:]
