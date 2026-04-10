"""
Screen Recorder — records the Android TV screen during test scenarios.
Uses `adb shell screenrecord` which saves MP4 video on the device,
then pulls it to the local output folder.

Limitations:
  - Max 180 seconds per file (Android limit) — auto-splits if longer
  - Requires Android 4.4+ (API 19) — ROD TV device is Android 12, fine
  - Records at 1280x720 to keep file sizes manageable
"""

import os
import subprocess
import threading
import time
import logging

logger = logging.getLogger(__name__)

RECORDINGS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "output", "recordings"
)
os.makedirs(RECORDINGS_DIR, exist_ok=True)


class ScreenRecorder:
    """
    Starts and stops screen recording on the Android TV device.
    Each scenario gets its own MP4 file.
    """

    MAX_DURATION = 170  # seconds — just under Android's 180s hard limit

    def __init__(self, device_target: str):
        self._target   = device_target
        self._proc     = None          # subprocess for adb shell screenrecord
        self._thread   = None          # thread monitoring the process
        self._device_path = ""         # path on device
        self._local_path  = ""         # path after pull
        self._recording   = False
        self._split_count = 0
        self._segment_paths = []       # all pulled segments for this scenario

    # ── Public API ────────────────────────────────────────────────────────

    def start(self, scenario_id: str, label: str = "") -> bool:
        """Start recording. Returns True if recording started successfully."""
        if self._recording:
            self.stop()

        self._split_count  = 0
        self._segment_paths = []
        self._scenario_id  = scenario_id
        self._label        = label or scenario_id

        return self._start_segment()

    def stop(self) -> str:
        """
        Stop recording and pull the video to local disk.
        Returns the local file path (or empty string on failure).
        """
        if not self._recording:
            return self._local_path

        self._recording = False

        # Send SIGINT to screenrecord to stop gracefully (flush final frames)
        try:
            subprocess.run(
                ["adb", "-s", self._target, "shell",
                 "pkill -INT screenrecord"],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass

        time.sleep(2)   # give device time to flush/close the file

        # Kill forcefully if still running
        try:
            subprocess.run(
                ["adb", "-s", self._target, "shell", "pkill screenrecord"],
                capture_output=True, timeout=3,
            )
        except Exception:
            pass

        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:
                pass
            self._proc = None

        # Pull the file from device
        pulled = self._pull(self._device_path, self._local_path)
        if pulled:
            self._segment_paths.append(self._local_path)

        # Clean up device file
        self._cleanup_device(self._device_path)

        if self._segment_paths:
            self._local_path = self._segment_paths[-1]
            logger.info(f"  Recording saved: {self._local_path}")
            return self._local_path
        return ""

    @property
    def local_path(self) -> str:
        return self._local_path

    @property
    def is_recording(self) -> bool:
        return self._recording

    # ── Internals ─────────────────────────────────────────────────────────

    def _start_segment(self) -> bool:
        """Start one recording segment on the device."""
        ts = time.strftime("%H%M%S")
        fname = f"{self._scenario_id}_{ts}_part{self._split_count}.mp4"
        self._device_path = f"/sdcard/{fname}"
        self._local_path  = os.path.join(RECORDINGS_DIR, fname)

        cmd = [
            "adb", "-s", self._target, "shell",
            "screenrecord",
            "--size", "1280x720",
            "--bit-rate", "2000000",    # 2 Mbps — good quality, small file
            "--time-limit", str(self.MAX_DURATION),
            self._device_path,
        ]

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._recording = True
            self._split_count += 1
            logger.info(f"  Screen recording started → {fname}")

            # Start watchdog thread that auto-restarts after MAX_DURATION
            self._thread = threading.Thread(
                target=self._watchdog, daemon=True
            )
            self._thread.start()
            return True

        except Exception as exc:
            logger.warning(f"  Screen recording failed to start: {exc}")
            self._recording = False
            return False

    def _watchdog(self):
        """
        Waits for the current segment to finish (MAX_DURATION),
        then pulls it and starts a new segment if still recording.
        """
        start = time.time()
        while self._recording:
            elapsed = time.time() - start
            if elapsed >= self.MAX_DURATION - 2:
                logger.info("  Recording segment limit reached — starting new segment")
                # Pull current segment
                self._pull(self._device_path, self._local_path)
                self._segment_paths.append(self._local_path)
                self._cleanup_device(self._device_path)
                # Start next segment
                self._start_segment()
                return
            time.sleep(2)

    def _pull(self, device_path: str, local_path: str) -> bool:
        """Pull a file from the device to local disk."""
        try:
            result = subprocess.run(
                ["adb", "-s", self._target, "pull", device_path, local_path],
                capture_output=True, timeout=60,
            )
            if result.returncode == 0 and os.path.exists(local_path):
                size_mb = os.path.getsize(local_path) / (1024 * 1024)
                logger.info(f"  Video pulled: {os.path.basename(local_path)} ({size_mb:.1f} MB)")
                return True
            else:
                logger.warning(f"  Pull failed: {result.stderr.decode()[:100]}")
                return False
        except Exception as exc:
            logger.warning(f"  Pull error: {exc}")
            return False

    def _cleanup_device(self, device_path: str):
        """Remove the recording file from the device."""
        try:
            subprocess.run(
                ["adb", "-s", self._target, "shell", f"rm -f {device_path}"],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass
